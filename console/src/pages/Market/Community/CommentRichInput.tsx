import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  type ClipboardEvent,
  type DragEvent,
  type KeyboardEvent,
} from "react";
import { customEmojiSrc, isAnimatedEmoji } from "./customEmoji";
import styles from "./index.module.less";

export interface CommentRichInputHandle {
  /** Inserts plain text at the caret (emoji picker unicode picks). */
  insertText: (text: string) => void;
  /** Inserts a custom emoji rendered as an image node inside the input. */
  insertEmoji: (url: string) => void;
  focus: () => void;
  /** Focuses and moves the caret to the end. */
  focusEnd: () => void;
}

interface CommentRichInputProps {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  maxLength?: number;
  disabled?: boolean;
  /** Minimum height in text rows (mirrors textarea rows). */
  rows?: number;
  /** Maximum height in text rows before the box scrolls internally. */
  maxRows?: number;
  ariaLabel?: string;
}

const EMOJI_TOKEN = /\[emoji:([^\]\n]+)\]/g;

/** DOM → text: text nodes verbatim, <br>/blocks as newlines, imgs as tokens. */
function serializeNode(node: Node, out: string[]): void {
  if (node.nodeType === 3) {
    out.push(node.textContent || "");
    return;
  }
  if (node.nodeType === 1 && (node as Element).tagName === "IMG") {
    const url = (node as Element).getAttribute("data-emoji-url");
    if (url) out.push(`[emoji:${url}]`);
    return;
  }
  if (node.nodeType === 1 && (node as Element).tagName === "BR") {
    out.push("\n");
    return;
  }
  if (
    node.nodeType === 1 &&
    ((node as Element).tagName === "DIV" || (node as Element).tagName === "P")
  ) {
    if (out.length > 0 && !out[out.length - 1].endsWith("\n")) {
      out.push("\n");
    }
    node.childNodes.forEach((child) => serializeNode(child, out));
    return;
  }
  node.childNodes.forEach((child) => serializeNode(child, out));
}

function serializeRichInput(root: Node): string {
  const out: string[] = [];
  root.childNodes.forEach((child) => serializeNode(child, out));
  return out.join("");
}

function buildEmojiImg(src: string): HTMLImageElement {
  const img = document.createElement("img");
  img.src = src;
  img.alt = "emoji";
  img.setAttribute("data-emoji-url", src);
  img.contentEditable = "false";
  img.draggable = false;
  // Same 66/150 split as rendered comments, mirroring platform-front.
  img.className = isAnimatedEmoji(src)
    ? styles.customAnimatedEmoji
    : styles.customEmoji;
  return img;
}

function sliceText(text: string, length: number): string {
  if (length <= 0) return "";
  if (text.length <= length) return text;
  let result = text.slice(0, length);
  // Do not leave an unmatched UTF-16 high surrogate at the limit.
  if (/[\uD800-\uDBFF]$/.test(result)) result = result.slice(0, -1);
  return result;
}

/** Truncation treats each [emoji:<url>] placeholder as one atomic node. */
function truncateSerializedValue(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  if (maxLength <= 0) return "";

  const tokenPattern = new RegExp(EMOJI_TOKEN.source, "g");
  let result = "";
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(value))) {
    const plain = value.slice(cursor, match.index);
    const remainingBeforePlain = maxLength - result.length;
    if (remainingBeforePlain <= 0) return result;
    if (plain.length > remainingBeforePlain) {
      return result + sliceText(plain, remainingBeforePlain);
    }
    result += plain;

    const token = match[0];
    if (token.length > maxLength - result.length) return result;
    result += token;
    cursor = match.index + token.length;
  }

  return result + sliceText(value.slice(cursor), maxLength - result.length);
}

/** Text → DOM: placeholders become emoji images, the rest text nodes. */
function renderValue(root: HTMLElement, value: string): void {
  root.textContent = "";
  if (!value) return;
  const parts = value.split(EMOJI_TOKEN);
  parts.forEach((part, index) => {
    if (!part) return;
    if (index % 2 === 1) {
      const src = customEmojiSrc(part);
      if (src) {
        root.appendChild(buildEmojiImg(src));
        return;
      }
      root.appendChild(document.createTextNode(`[emoji:${part}]`));
      return;
    }
    root.appendChild(document.createTextNode(part));
  });
}

function placeCaretEnd(root: HTMLElement): void {
  const sel = window.getSelection();
  if (!sel) return;
  const range = document.createRange();
  range.selectNodeContents(root);
  range.collapse(false);
  sel.removeAllRanges();
  sel.addRange(range);
}

function isRangeInside(root: HTMLElement, range: Range): boolean {
  const common = range.commonAncestorContainer;
  const start = range.startContainer;
  const end = range.endContainer;
  return (
    (common === root || root.contains(common)) &&
    (start === root || root.contains(start)) &&
    (end === root || root.contains(end))
  );
}

/** Current selection inside the root, else the range saved before blur. */
function caretRangeInside(root: HTMLElement, savedRange: Range | null): Range {
  const sel = window.getSelection();
  if (sel && sel.rangeCount > 0) {
    const range = sel.getRangeAt(0);
    if (isRangeInside(root, range)) return range.cloneRange();
  }
  if (savedRange && isRangeInside(root, savedRange)) {
    return savedRange.cloneRange();
  }
  const range = document.createRange();
  range.selectNodeContents(root);
  range.collapse(false);
  return range;
}

function serializeRange(range: Range): string {
  const holder = document.createElement("div");
  holder.appendChild(range.cloneContents());
  return serializeRichInput(holder);
}

/**
 * Rich comment input (contenteditable), ported from platform-front: custom
 * emojis show as inline images while typing, yet the controlled value stays
 * the [emoji:<url>] shortcode protocol used for submission and rendering.
 */
const CommentRichInput = forwardRef<
  CommentRichInputHandle,
  CommentRichInputProps
>(function CommentRichInput(
  {
    value,
    onChange,
    placeholder,
    maxLength,
    disabled = false,
    rows = 3,
    maxRows = 12,
    ariaLabel,
  },
  ref,
) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const savedRangeRef = useRef<Range | null>(null);
  const composingRef = useRef(false);

  const rememberSelection = () => {
    const root = rootRef.current;
    const selection = window.getSelection();
    if (!root || !selection || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    if (isRangeInside(root, range)) {
      savedRangeRef.current = range.cloneRange();
    }
  };

  const emit = () => {
    const root = rootRef.current;
    if (!root) return;
    // Let the browser finish IME composition before rebuilding or
    // serializing the editable DOM; rebuilding during composition can
    // discard the candidate text and move the caret.
    if (composingRef.current) return;
    let next = serializeRichInput(root);
    if (typeof maxLength === "number" && next.length > maxLength) {
      next = truncateSerializedValue(next, maxLength);
      renderValue(root, next);
      placeCaretEnd(root);
      rememberSelection();
    }
    // Browsers may leave <br>/<div><br></div> behind after clearing the
    // editable; they serialize as newlines and break placeholder/count.
    const hasText = Boolean(root.textContent);
    const hasEmoji = Boolean(root.querySelector("img[data-emoji-url]"));
    if (!hasText && !hasEmoji && root.childNodes.length > 0) {
      root.textContent = "";
      next = "";
    }
    rememberSelection();
    onChange(next);
  };

  // External value changes (reset/prefill) rebuild the DOM when divergent.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    if (composingRef.current) return;
    if (serializeRichInput(root) !== value) {
      renderValue(root, value);
      // The old Range points at detached DOM after an external reset.
      savedRangeRef.current = null;
    }
  }, [value]);

  const insertNode = (node: Node, insertedLength: number) => {
    const root = rootRef.current;
    if (!root || disabled) return;

    const range = caretRangeInside(root, savedRangeRef.current);
    const currentLength = serializeRichInput(root).length;
    const selectedLength = serializeRange(range).length;
    const available =
      typeof maxLength === "number"
        ? maxLength - currentLength + selectedLength
        : Number.POSITIVE_INFINITY;
    if (available <= 0) return;

    if (node.nodeType === 3 && insertedLength > available) {
      const text = sliceText(node.textContent || "", available);
      if (!text) return;
      node = document.createTextNode(text);
      insertedLength = text.length;
    } else if (insertedLength > available) {
      // Images represent one atomic [emoji:<url>] token; never insert a
      // partial token and let the subsequent max-length pass corrupt it.
      return;
    }

    root.focus();
    range.deleteContents();
    range.insertNode(node);
    range.setStartAfter(node);
    range.collapse(true);
    const sel = window.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(range);
    savedRangeRef.current = range.cloneRange();
    emit();
  };

  useImperativeHandle(ref, () => ({
    insertText: (text: string) => {
      if (text) insertNode(document.createTextNode(text), text.length);
    },
    insertEmoji: (url: string) => {
      if (customEmojiSrc(url)) {
        insertNode(buildEmojiImg(url), `[emoji:${url}]`.length);
      }
    },
    focus: () => rootRef.current?.focus(),
    focusEnd: () => {
      const root = rootRef.current;
      if (!root) return;
      root.focus();
      placeCaretEnd(root);
      rememberSelection();
    },
  }));

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Enter inserts a plain newline text node instead of browser <div>/<br>
    // soup; never intercept while an IME composition is active.
    if (
      event.key === "Enter" &&
      !event.nativeEvent.isComposing &&
      !composingRef.current
    ) {
      event.preventDefault();
      insertNode(document.createTextNode("\n"), 1);
    }
  };

  const handleCompositionStart = () => {
    composingRef.current = true;
    rememberSelection();
  };

  const handleCompositionEnd = () => {
    composingRef.current = false;
    emit();
    rememberSelection();
  };

  const handlePaste = (event: ClipboardEvent<HTMLDivElement>) => {
    event.preventDefault();
    const text = event.clipboardData.getData("text/plain");
    if (text) {
      const normalized = text.replace(/\r\n?/g, "\n");
      insertNode(document.createTextNode(normalized), normalized.length);
    }
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    // Comment images must go through the upload flow; never let native
    // HTML/blob drops desynchronize the editable DOM from the value.
    event.preventDefault();
  };

  return (
    <div
      ref={rootRef}
      contentEditable={!disabled}
      suppressContentEditableWarning
      role="textbox"
      aria-multiline="true"
      aria-label={ariaLabel}
      aria-disabled={disabled}
      data-placeholder={placeholder}
      onInput={emit}
      onKeyDown={handleKeyDown}
      onPaste={handlePaste}
      onDragOver={(event) => event.preventDefault()}
      onDrop={handleDrop}
      onCompositionStart={handleCompositionStart}
      onCompositionEnd={handleCompositionEnd}
      onSelect={rememberSelection}
      onMouseUp={rememberSelection}
      onKeyUp={rememberSelection}
      onBlur={rememberSelection}
      style={{ minHeight: rows * 22, maxHeight: maxRows * 22 }}
      className={styles.richInput}
    />
  );
});

export default CommentRichInput;

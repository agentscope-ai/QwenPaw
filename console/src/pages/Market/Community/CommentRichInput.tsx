import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  type ClipboardEvent,
  type DragEvent,
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
    const block = node as Element;
    // Each block is one line; an empty block still separates its neighbors.
    if (out.length > 0) out.push("\n");
    // An empty block line carries a placeholder <br>; count the line once.
    if (block.childNodes.length === 1 && block.firstChild?.nodeName === "BR") {
      return;
    }
    block.childNodes.forEach((child, index, siblings) => {
      // A trailing <br> in a block is a caret placeholder, not a line break.
      if (child.nodeName === "BR" && index === siblings.length - 1) return;
      serializeNode(child, out);
    });
    return;
  }
  node.childNodes.forEach((child) => serializeNode(child, out));
}

function serializeRichInput(root: Node): string {
  const out: string[] = [];
  root.childNodes.forEach((child) => serializeNode(child, out));
  let result = out.join("");
  // A root-level trailing <br> is the caret placeholder that keeps the
  // final empty line focusable: renderValue appends it for values ending
  // in "\n" and Chromium keeps one after a native Enter. It is structure,
  // never content, so exactly one of them does not serialize.
  if (result.endsWith("\n") && root.lastChild?.nodeName === "BR") {
    result = result.slice(0, -1);
  }
  return result;
}

/*
 * The only place an emoji URL may reach img.src; re-gates here so the
 * allowlist invariant holds even if a future caller forgets to check.
 */
function buildEmojiImg(raw: string): HTMLImageElement | null {
  const src = customEmojiSrc(raw);
  if (!src) return null;
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

/**
 * Text → DOM: placeholders become emoji images and newlines become <br>,
 * so line ends keep a rendered caret anchor (a trailing "\n" text node
 * loses the caret to gravity in Chromium); the rest stays text nodes.
 */
function appendTextWithBreaks(root: HTMLElement, text: string): void {
  text.split("\n").forEach((line, index) => {
    if (index > 0) root.appendChild(document.createElement("br"));
    if (line) root.appendChild(document.createTextNode(line));
  });
}

function renderValue(root: HTMLElement, value: string): void {
  root.textContent = "";
  if (!value) return;
  const parts = value.split(EMOJI_TOKEN);
  parts.forEach((part, index) => {
    if (!part) return;
    if (index % 2 === 1) {
      const img = buildEmojiImg(part);
      if (img) {
        root.appendChild(img);
        return;
      }
      appendTextWithBreaks(root, `[emoji:${part}]`);
      return;
    }
    appendTextWithBreaks(root, part);
  });
  // A lone trailing <br> renders no focusable empty last line (Chromium
  // treats it as the caret placeholder); mirror the browser's own Enter
  // output so restored drafts ending in "\n" keep a real second line.
  if (root.lastChild?.nodeName === "BR") {
    root.appendChild(document.createElement("br"));
  }
}

/**
 * Range at the end of the content, before any trailing caret-placeholder
 * <br> — where the browser itself puts the caret when the last line is
 * empty. Inserting after the placeholder would strand content behind it.
 */
function endCaretRange(root: HTMLElement): Range {
  const range = document.createRange();
  const last = root.lastChild;
  if (last?.nodeName === "BR") {
    range.setEndBefore(last);
    range.collapse(false);
    return range;
  }
  range.selectNodeContents(root);
  range.collapse(false);
  return range;
}

function placeCaretEnd(root: HTMLElement): void {
  const sel = window.getSelection();
  if (!sel) return;
  const range = endCaretRange(root);
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
  return endCaretRange(root);
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
 * Enter and paste ride the browser editing pipeline (native undo stack and
 * stable caret anchors); serialization maps <br>/block soup back to "\n".
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

  /** Plain-text insertion routed through the browser editing transaction. */
  const insertPlainText = (text: string) => {
    const root = rootRef.current;
    if (!root || disabled || !text) return;
    root.focus();
    // Restore the saved caret when the live selection drifted elsewhere.
    const sel = window.getSelection();
    const current = sel && sel.rangeCount > 0 ? sel.getRangeAt(0) : null;
    if (!current || !isRangeInside(root, current)) {
      const saved = savedRangeRef.current;
      if (saved && isRangeInside(root, saved)) {
        sel?.removeAllRanges();
        sel?.addRange(saved.cloneRange());
      }
    }
    // execCommand replaces the selection inside the native undo stack; a
    // successful command fires input, which runs emit() for us. jsdom and
    // hardened environments lack it, so fall back to the manual range.
    let handled = false;
    try {
      handled = document.execCommand("insertText", false, text);
    } catch {
      handled = false;
    }
    if (handled) return;
    insertNode(document.createTextNode(text), text.length);
  };

  useImperativeHandle(ref, () => ({
    insertText: (text: string) => {
      insertPlainText(text);
    },
    insertEmoji: (url: string) => {
      const img = buildEmojiImg(url);
      if (img) insertNode(img, `[emoji:${url}]`.length);
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
    // Plain text only; the editing transaction keeps paste undoable.
    event.preventDefault();
    const text = event.clipboardData.getData("text/plain");
    if (text) insertPlainText(text.replace(/\r\n?/g, "\n"));
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

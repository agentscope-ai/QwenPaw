import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import i18n from "@/i18n";
import type { PromptRichToken } from "./PromptRichBlock";

export interface PromptTokenEditorHandle {
  insertToken: (index: number) => void;
  getValue: () => string;
  focus: () => void;
}

// Complete literals so Tailwind ships the classes injected into editor DOM.
const TOKEN_PILL_CLASS =
  "prompt-token-pill mx-0.5 inline-flex cursor-pointer select-none items-center gap-1 rounded-full border border-[color-mix(in_srgb,var(--color-accent)_35%,var(--color-border))] bg-[var(--color-bg-primary)] py-0.5 pl-0.5 pr-2 align-[-5px] text-[11px] leading-none shadow-xs hover:border-[var(--color-danger)]";
const TOKEN_IMG_CLASS =
  "h-5 w-5 rounded-full border border-[var(--color-border)] object-cover";
const TOKEN_INDEX_CLASS =
  "font-mono text-[9px] font-bold text-[var(--color-accent)]";
const TOKEN_NAME_CLASS =
  "max-w-[108px] truncate font-medium text-[var(--color-text-primary)]";

function createTokenPill(token: PromptRichToken): HTMLSpanElement {
  const pill = document.createElement("span");
  pill.className = TOKEN_PILL_CLASS;
  pill.contentEditable = "false";
  pill.dataset.imageIndex = String(token.index);
  pill.title = i18n.t("r2v.tokenClickRemove");
  if (token.thumbUrl) {
    const img = document.createElement("img");
    img.src = token.thumbUrl;
    img.alt = "";
    img.className = TOKEN_IMG_CLASS;
    pill.append(img);
  }
  const indexBadge = document.createElement("span");
  indexBadge.className = TOKEN_INDEX_CLASS;
  indexBadge.textContent = `IMG ${token.index}`;
  const name = document.createElement("span");
  name.className = TOKEN_NAME_CLASS;
  name.textContent = token.name;
  pill.append(indexBadge, name);
  return pill;
}

/** Editor DOM → prompt text: pills serialize back to [Image N] literals. */
function serialize(root: HTMLElement): string {
  let text = "";
  const walk = (node: Node) => {
    node.childNodes.forEach((child) => {
      if (child.nodeType === Node.TEXT_NODE) {
        text += child.textContent ?? "";
        return;
      }
      if (child.nodeType !== Node.ELEMENT_NODE) return;
      const element = child as HTMLElement;
      if (element.dataset.imageIndex) {
        text += `[Image ${element.dataset.imageIndex}]`;
        return;
      }
      if (element.tagName === "BR") {
        text += "\n";
        return;
      }
      const block = element.tagName === "DIV" || element.tagName === "P";
      if (block && text && !text.endsWith("\n")) text += "\n";
      walk(element);
    });
  };
  walk(root);
  return text.replace(/\u00a0/g, " ");
}

/**
 * Fullscreen prompt editor surface: a contenteditable whose [Image N]
 * citations live as thumbnail pills (the same visual as the read preview),
 * so inserting a reference drops the pill itself — not a bare marker.
 * Clicking a pill removes it. Value serializes back to plain prompt text.
 */
const PromptTokenEditor = forwardRef<
  PromptTokenEditorHandle,
  {
    initialValue: string;
    tokens: PromptRichToken[];
    disabled?: boolean;
    onChange: (value: string) => void;
  }
>(function PromptTokenEditor(
  { initialValue, tokens, disabled, onChange },
  ref,
) {
  const editorRef = useRef<HTMLDivElement>(null);
  const savedRange = useRef<Range | null>(null);
  const tokensRef = useRef(tokens);
  tokensRef.current = tokens;

  // Deserialize once per mount (the fullscreen modal remounts per opening);
  // afterwards the DOM is the source of truth and only serializes outward.
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.innerHTML = "";
    for (const part of initialValue.split(/(\[Image \d+\])/)) {
      const match = /^\[Image (\d+)\]$/.exec(part);
      if (match) {
        const token = tokensRef.current.find(
          (item) => item.index === Number(match[1]),
        );
        if (token) {
          editor.append(createTokenPill(token));
          continue;
        }
      }
      if (part) editor.append(document.createTextNode(part));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const emit = () => {
    if (editorRef.current) onChange(serialize(editorRef.current));
  };

  const saveRange = () => {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    if (editorRef.current?.contains(range.commonAncestorContainer)) {
      savedRange.current = range.cloneRange();
    }
  };

  const insertionRange = (): Range | null => {
    const editor = editorRef.current;
    if (!editor) return null;
    editor.focus();
    const selection = window.getSelection();
    if (
      selection?.rangeCount &&
      editor.contains(selection.getRangeAt(0).commonAncestorContainer)
    ) {
      return selection.getRangeAt(0);
    }
    if (
      savedRange.current &&
      editor.contains(savedRange.current.commonAncestorContainer)
    ) {
      return savedRange.current;
    }
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    return range;
  };

  useImperativeHandle(ref, () => ({
    insertToken: (index: number) => {
      const token = tokensRef.current.find((item) => item.index === index);
      if (!token) return;
      const range = insertionRange();
      if (!range) return;
      range.deleteContents();
      const pill = createTokenPill(token);
      range.insertNode(pill);
      const space = document.createTextNode("\u00a0");
      pill.after(space);
      const after = document.createRange();
      after.setStartAfter(space);
      after.collapse(true);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(after);
      savedRange.current = after.cloneRange();
      emit();
    },
    getValue: () =>
      editorRef.current ? serialize(editorRef.current) : initialValue,
    focus: () => editorRef.current?.focus(),
  }));

  const handleClick = (event: ReactMouseEvent<HTMLDivElement>) => {
    const pill = (event.target as HTMLElement).closest?.("[data-image-index]");
    if (pill && editorRef.current?.contains(pill)) {
      pill.remove();
      emit();
    }
    saveRange();
  };

  return (
    <div
      ref={editorRef}
      data-prompt-token-editor
      contentEditable={!disabled}
      suppressContentEditableWarning
      role="textbox"
      aria-multiline="true"
      onInput={() => {
        saveRange();
        emit();
      }}
      onKeyUp={saveRange}
      onMouseUp={saveRange}
      onBlur={saveRange}
      onClick={handleClick}
      className="min-h-[360px] w-full flex-1 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2.5 text-xs leading-[2] text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
    />
  );
});

export default PromptTokenEditor;

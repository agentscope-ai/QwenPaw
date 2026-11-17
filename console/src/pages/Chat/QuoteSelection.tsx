import { Button } from "antd";
import { Quote } from "lucide-react";
import { useEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { setTextareaValue } from "./utils";

const excluded =
  'button, [role="button"], input, textarea, [contenteditable], header, iframe';
const parentElement = (node: Node) =>
  node instanceof Element ? node : node.parentElement;

export function QuoteSelection({
  containerRef,
  scopeKey,
  enabled,
}: {
  containerRef: RefObject<HTMLDivElement>;
  scopeKey: string;
  enabled: boolean;
}) {
  const { t } = useTranslation();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [selection, setSelection] = useState<{
    text: string;
    top: number;
    left: number;
    scopeKey: string;
  }>();
  const current =
    enabled && selection?.scopeKey === scopeKey ? selection : undefined;

  useEffect(() => {
    setSelection(undefined);
    if (!enabled) return;
    const update = () => {
      if (document.activeElement === buttonRef.current) return;
      const selected = window.getSelection();
      const range =
        selected?.rangeCount === 1 ? selected.getRangeAt(0) : undefined;
      const start = range && parentElement(range.startContainer);
      const end = range && parentElement(range.endContainer);
      const response = start?.closest('[data-quote-response="true"]');
      if (
        !range ||
        !selected ||
        selected.isCollapsed ||
        !response ||
        !containerRef.current?.contains(response) ||
        response !== end?.closest('[data-quote-response="true"]') ||
        start?.closest(excluded) ||
        end?.closest(excluded) ||
        !selected.toString().trim()
      ) {
        setSelection(undefined);
        return;
      }
      const rect = range.getBoundingClientRect();
      setSelection({
        text: selected.toString(),
        scopeKey,
        left: Math.max(8, Math.min(rect.left, window.innerWidth - 210)),
        top: Math.max(
          8,
          Math.min(
            rect.top >= 52 ? rect.top - 44 : rect.bottom + 8,
            window.innerHeight - 48,
          ),
        ),
      });
    };
    const dismiss = () => setSelection(undefined);
    document.addEventListener("selectionchange", update);
    window.addEventListener("resize", dismiss);
    window.addEventListener("scroll", dismiss, true);
    return () => {
      document.removeEventListener("selectionchange", update);
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("scroll", dismiss, true);
    };
  }, [containerRef, enabled, scopeKey]);

  const quote = () => {
    const textarea = containerRef.current?.querySelector<HTMLTextAreaElement>(
      "textarea[data-quote-composer]",
    );
    if (!current || !textarea || textarea.disabled || textarea.readOnly) return;
    const blockquote = current.text
      .replace(/\r\n?/g, "\n")
      .split("\n")
      .map((line) => `> ${line}`)
      .join("\n");
    const draft = textarea.value;
    const separator = draft && !draft.endsWith("\n\n") ? "\n\n" : "";
    setTextareaValue(textarea, `${draft}${separator}${blockquote}\n\n`);
    window.getSelection()?.removeAllRanges();
    setSelection(undefined);
    textarea.focus();
  };

  useEffect(() => {
    if (!current) return;
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelection(undefined);
      else if (
        event.altKey &&
        event.shiftKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        (event.code === "KeyQ" || event.key.toLowerCase() === "q")
      ) {
        event.preventDefault();
        quote();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  });

  return current
    ? createPortal(
        <Button
          ref={buttonRef}
          type="primary"
          icon={<Quote size={16} aria-hidden />}
          aria-keyshortcuts="Alt+Shift+Q"
          style={{
            position: "fixed",
            zIndex: 1000,
            left: current.left,
            top: current.top,
            minHeight: 36,
            maxWidth: "calc(100vw - 16px)",
          }}
          onPointerDown={(event) => event.preventDefault()}
          onClick={quote}
        >
          {t("chat.quoteFollowUp")}
        </Button>,
        document.body,
      )
    : null;
}

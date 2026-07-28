import { createPortal } from "react-dom";
import { useEffect, useState, type CSSProperties } from "react";
import {
  atomicDeletionRange,
  type ParsedFileReference,
  splitFileReferences,
} from "./fileReferenceFormatting";
import { getActiveSenderTextarea } from "./utils";
import styles from "./index.module.less";

interface OverlayState {
  host: HTMLElement;
  scrollTop: number;
  scrollLeft: number;
  style: CSSProperties;
}

function overlayStyle(textarea: HTMLTextAreaElement): CSSProperties {
  const computed = window.getComputedStyle(textarea);
  return {
    top: textarea.offsetTop,
    left: textarea.offsetLeft,
    width: textarea.offsetWidth,
    height: textarea.offsetHeight,
    padding: computed.padding,
    borderWidth: computed.borderWidth,
    borderStyle: "solid",
    borderColor: "transparent",
    boxSizing: computed.boxSizing as CSSProperties["boxSizing"],
    font: computed.font,
    letterSpacing: computed.letterSpacing,
    lineHeight: computed.lineHeight,
    textAlign: computed.textAlign as CSSProperties["textAlign"],
    textIndent: computed.textIndent,
    tabSize: computed.tabSize,
  };
}

export default function FileReferenceInputOverlay({
  value,
  onOpenReference,
}: {
  value: string;
  onOpenReference?: (
    reference: ParsedFileReference,
    trigger: HTMLElement,
  ) => void;
}) {
  const [state, setState] = useState<OverlayState | null>(null);

  useEffect(() => {
    let textarea: HTMLTextAreaElement | null = null;
    let resizeObserver: ResizeObserver | null = null;

    const sync = () => {
      if (!textarea?.isConnected || !textarea.parentElement) return;
      setState({
        host: textarea.parentElement,
        scrollTop: textarea.scrollTop,
        scrollLeft: textarea.scrollLeft,
        style: overlayStyle(textarea),
      });
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        !textarea ||
        (event.key !== "Backspace" && event.key !== "Delete") ||
        event.isComposing ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey
      ) {
        return;
      }
      const range = atomicDeletionRange(
        textarea.value,
        textarea.selectionStart ?? 0,
        textarea.selectionEnd ?? 0,
        event.key,
      );
      if (!range) return;
      event.preventDefault();
      textarea.setRangeText("", range.start, range.end, "end");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      sync();
    };

    const detach = () => {
      if (!textarea) return;
      textarea.classList.remove(styles.fileReferenceTextarea);
      textarea.parentElement?.classList.remove(styles.fileReferenceHost);
      textarea.removeEventListener("input", sync);
      textarea.removeEventListener("scroll", sync);
      textarea.removeEventListener("keydown", handleKeyDown);
      resizeObserver?.disconnect();
      resizeObserver = null;
      textarea = null;
    };

    const attach = () => {
      const next = getActiveSenderTextarea();
      if (!next || next === textarea) return;
      detach();
      textarea = next;
      textarea.classList.add(styles.fileReferenceTextarea);
      textarea.parentElement?.classList.add(styles.fileReferenceHost);
      textarea.addEventListener("input", sync);
      textarea.addEventListener("scroll", sync);
      textarea.addEventListener("keydown", handleKeyDown);
      resizeObserver = new ResizeObserver(sync);
      resizeObserver.observe(textarea);
      sync();
    };

    attach();
    const observer = new MutationObserver(attach);
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener("focusin", attach);
    window.addEventListener("resize", sync);
    return () => {
      observer.disconnect();
      document.removeEventListener("focusin", attach);
      window.removeEventListener("resize", sync);
      detach();
    };
  }, []);

  if (!state) return null;
  return createPortal(
    <div className={styles.fileReferenceOverlay} style={state.style}>
      <div
        className={styles.fileReferenceOverlayContent}
        style={{
          transform: `translate(${-state.scrollLeft}px, ${-state.scrollTop}px)`,
        }}
      >
        {splitFileReferences(value).map((segment, index) =>
          segment.reference ? (
            <button
              type="button"
              className={styles.inlineFileReference}
              key={`${index}-${segment.text}`}
              tabIndex={-1}
              onMouseDown={(event) => event.preventDefault()}
              onClick={(event) =>
                onOpenReference?.(segment.reference!, event.currentTarget)
              }
            >
              {segment.text}
            </button>
          ) : (
            <span aria-hidden="true" key={`${index}-${segment.text}`}>
              {segment.text}
            </span>
          ),
        )}
      </div>
    </div>,
    state.host,
  );
}

/**
 * Text-selection toolbar.  The toolbar anchors to the end of the selection
 * (top-right of the last selected line) and only flips to the other side when
 * the viewport edge would clip it, so it never covers the selected content.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { MessageSquarePlus } from "lucide-react";
import {
  useAgentDockUiStore,
  type SelectionAttachment,
} from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useOnboardingStore } from "@/store/onboardingStore";

interface ToolbarAnchor {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

interface ToolbarState {
  anchor: ToolbarAnchor;
  sel: SelectionAttachment;
}

function pointAnchor(x: number, y: number): ToolbarAnchor {
  const px = Number.isFinite(x) ? x : 8;
  const py = Number.isFinite(y) ? y : 54;
  return { left: px, top: py, right: px, bottom: py };
}

function rangeEndAnchor(range: Range): ToolbarAnchor {
  const rects =
    typeof range.getClientRects === "function"
      ? Array.from(range.getClientRects()).filter(
          (rect) => rect.width > 0 || rect.height > 0,
        )
      : [];
  const rect = rects[rects.length - 1] ?? range.getBoundingClientRect();
  return {
    left: rect.left,
    top: rect.top,
    right: rect.right,
    bottom: rect.bottom,
  };
}

function locateField(element: Element | null): {
  field: string | null;
  path: string | null;
  label: string;
} {
  const region = element?.closest?.(
    "[data-creator-field]",
  ) as HTMLElement | null;
  if (!region) return { field: null, path: null, label: "页面选中文本" };
  return {
    field: region.getAttribute("data-creator-field"),
    path: region.getAttribute("data-creator-path"),
    label: region.getAttribute("data-creator-field-label") || "选中文本",
  };
}

function refOfField(field: string | null): string | null {
  return field?.split("/")[0] || null;
}

function shouldIgnoreSelectionIn(element: Element | null): boolean {
  return Boolean(element?.closest?.("[data-agent-dock]"));
}

export default function SelectionToolbar() {
  const [state, setState] = useState<ToolbarState | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const lastPointRef = useRef<{ x: number; y: number } | null>(null);
  const setDockSelection = useAgentDockUiStore((item) => item.setSelection);

  useEffect(() => {
    const compute = (clientX: number, clientY: number): ToolbarState | null => {
      const active = document.activeElement;
      if (active && shouldIgnoreSelectionIn(active)) return null;

      if (
        active &&
        (active.tagName === "TEXTAREA" || active.tagName === "INPUT")
      ) {
        const input = active as HTMLTextAreaElement | HTMLInputElement;
        const start = input.selectionStart ?? 0;
        const end = input.selectionEnd ?? 0;
        if (end > start) {
          const { field, path, label } = locateField(input);
          if (!field) return null;
          return {
            anchor: pointAnchor(clientX, clientY),
            sel: {
              text: input.value.slice(start, end),
              ref: refOfField(field),
              field,
              path,
              start,
              end,
              label,
            },
          };
        }
      }

      const selection = window.getSelection();
      if (selection && selection.rangeCount > 0 && !selection.isCollapsed) {
        const text = selection.toString();
        if (text.trim()) {
          const range = selection.getRangeAt(0);
          const startNode = range.startContainer;
          const element =
            startNode.nodeType === Node.TEXT_NODE
              ? startNode.parentElement
              : (startNode as Element);
          if (shouldIgnoreSelectionIn(element)) return null;
          const region = element?.closest?.(
            "[data-creator-field]",
          ) as HTMLElement | null;
          const field = region?.getAttribute("data-creator-field") ?? null;
          const path = region?.getAttribute("data-creator-path") ?? null;
          const label =
            region?.getAttribute("data-creator-field-label") || "选中文本";
          if (!region || !field) return null;
          if (
            !region.contains(range.startContainer) ||
            !region.contains(range.endContainer)
          )
            return null;
          const before = range.cloneRange();
          before.selectNodeContents(region);
          before.setEnd(range.startContainer, range.startOffset);
          const start = before.toString().length;
          if (start < 0) return null;
          return {
            anchor: rangeEndAnchor(range),
            sel: {
              text,
              ref: refOfField(field),
              field,
              path,
              start,
              end: start + text.length,
              label,
            },
          };
        }
      }
      return null;
    };

    const onMouseUp = (event: MouseEvent) => {
      if (barRef.current?.contains(event.target as Node)) return;
      lastPointRef.current = { x: event.clientX, y: event.clientY };
      window.setTimeout(
        () => setState(compute(event.clientX, event.clientY)),
        0,
      );
    };
    const onSelectionChange = () => {
      const active = document.activeElement as HTMLElement | null;
      if (shouldIgnoreSelectionIn(active)) return;
      window.setTimeout(() => {
        const latest = lastPointRef.current;
        if (
          active &&
          (active.tagName === "TEXTAREA" || active.tagName === "INPUT")
        ) {
          const rect = active.getBoundingClientRect();
          setState(
            compute(
              latest?.x ?? rect.left + Math.min(120, rect.width / 2),
              latest?.y ?? rect.top + 8,
            ),
          );
          return;
        }
        const selection = window.getSelection();
        if (selection && selection.rangeCount > 0 && !selection.isCollapsed) {
          const rect = selection.getRangeAt(0).getBoundingClientRect();
          setState(
            compute(
              latest?.x ?? rect.left + rect.width / 2,
              latest?.y ?? rect.top,
            ),
          );
        }
      }, 0);
    };
    const close = () => setState(null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };

    document.addEventListener("mouseup", onMouseUp);
    document.addEventListener("selectionchange", onSelectionChange);
    document.addEventListener("scroll", close, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mouseup", onMouseUp);
      document.removeEventListener("selectionchange", onSelectionChange);
      document.removeEventListener("scroll", close, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  useLayoutEffect(() => {
    if (!state) {
      setPos(null);
      return;
    }
    const bar = barRef.current;
    const width = bar?.offsetWidth || 116;
    const height = bar?.offsetHeight || 32;
    const gap = 6;
    const { anchor } = state;
    // Default to the top-right of the selection end so it doesn't cover what
    // was just selected; shift left when short on right-side space, flip below
    // the selection when short on space above.
    let left = anchor.right + gap;
    if (left + width > window.innerWidth - 8) left = anchor.right - width;
    left = Math.min(
      Math.max(left, 8),
      Math.max(8, window.innerWidth - width - 8),
    );
    let top = anchor.top - height - gap;
    if (top < 8) top = anchor.bottom + gap;
    top = Math.min(
      Math.max(top, 8),
      Math.max(8, window.innerHeight - height - 8),
    );
    setPos({ left, top });
  }, [state]);

  if (!state) return null;

  const addToConversation = () => {
    useOnboardingStore.getState().markHintSeen("addToConversation");
    setDockSelection(state.sel);
    useCreatorInteractionStore.getState().setSelection(state.sel);
    setState(null);
    window.getSelection()?.removeAllRanges();
  };

  return (
    <div
      ref={barRef}
      style={{
        position: "fixed",
        top: pos?.top ?? -9999,
        left: pos?.left ?? -9999,
        visibility: pos ? "visible" : "hidden",
        // Above the tour mask and popover (antd Tour defaults to 1001) so the bar
        // is visible during the onboarding tour's real-selection demo.
        zIndex: 1100,
      }}
      className="agent-dock-enter flex flex-col overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] p-0.5 shadow-lg"
    >
      <button
        type="button"
        onMouseDown={(event) => event.preventDefault()}
        onClick={addToConversation}
        className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-[var(--color-text-primary)] transition-colors hover:bg-[var(--color-accent-soft)] hover:text-[var(--color-accent)]"
      >
        <MessageSquarePlus className="h-3.5 w-3.5" />
        添加到对话
      </button>
    </div>
  );
}

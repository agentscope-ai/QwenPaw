import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ReactNode, RefObject } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import styles from "../index.module.less";

const CODE_BLOCK_SELECTOR = ".qwenpaw-codeHighlighter";
const CODE_BODY_SELECTOR = ".qwenpaw-codeHighlighter-code";
const CODE_ACTIONS_SELECTOR = ".qwenpaw-code-header-actions";
const VISIBLE_LINES = 5;

interface Labels {
  collapse: string;
  expand: string;
}

interface CodeBlockTarget {
  id: string;
  actions: HTMLElement;
  block: HTMLElement;
  lineCount: number;
}

function countLines(text: string): number {
  const normalized = text.replace(/\r\n?/g, "\n").replace(/\n$/, "");
  if (!normalized) return 0;
  return normalized.split("\n").length;
}

function sameTargets(left: CodeBlockTarget[], right: CodeBlockTarget[]) {
  return (
    left.length === right.length &&
    left.every((target, index) => {
      const other = right[index];
      return (
        target.id === other.id &&
        target.actions === other.actions &&
        target.block === other.block &&
        target.lineCount === other.lineCount
      );
    })
  );
}

export function useCollapsibleCodeBlocks(
  containerRef: RefObject<HTMLElement | null>,
  labels: Labels,
): ReactNode {
  const [targets, setTargets] = useState<CodeBlockTarget[]>([]);
  const [collapsedById, setCollapsedById] = useState<Record<string, boolean>>(
    {},
  );
  const collapsedByIdRef = useRef(collapsedById);
  const blockIdsRef = useRef(new Map<HTMLElement, string>());
  const nextIdRef = useRef(0);

  useEffect(() => {
    collapsedByIdRef.current = collapsedById;
  }, [collapsedById]);

  const scan = useCallback(() => {
    const root = containerRef.current;
    if (!root) {
      setTargets((current) => (current.length ? [] : current));
      return;
    }

    const nextTargets: CodeBlockTarget[] = [];
    const blocks = root.querySelectorAll<HTMLElement>(CODE_BLOCK_SELECTOR);

    blocks.forEach((block) => {
      const body = block.querySelector<HTMLElement>(CODE_BODY_SELECTOR);
      const actions = block.querySelector<HTMLElement>(CODE_ACTIONS_SELECTOR);
      if (!body || !actions) return;

      const lineCount = countLines(body.textContent ?? "");
      if (lineCount <= VISIBLE_LINES) {
        block.removeAttribute("data-qwenpaw-code-collapsible");
        block.removeAttribute("data-qwenpaw-code-collapsed");
        return;
      }

      let id = blockIdsRef.current.get(block);
      if (!id) {
        nextIdRef.current += 1;
        id = `qwenpaw-code-block-${nextIdRef.current}`;
        blockIdsRef.current.set(block, id);
      }

      const collapsed = collapsedByIdRef.current[id] ?? true;
      if (block.dataset.qwenpawCodeCollapsible !== "true") {
        block.dataset.qwenpawCodeCollapsible = "true";
      }
      const collapsedValue = String(collapsed);
      if (block.dataset.qwenpawCodeCollapsed !== collapsedValue) {
        block.dataset.qwenpawCodeCollapsed = collapsedValue;
      }
      block.style.setProperty(
        "--qwenpaw-code-collapsed-lines",
        String(VISIBLE_LINES),
      );

      nextTargets.push({ id, actions, block, lineCount });
    });

    Array.from(blockIdsRef.current.keys()).forEach((block) => {
      if (!root.contains(block)) {
        blockIdsRef.current.delete(block);
      }
    });

    setTargets((current) =>
      sameTargets(current, nextTargets) ? current : nextTargets,
    );
  }, [containerRef]);

  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;

    let timer: number | null = null;
    const scheduleScan = () => {
      if (timer !== null) return;
      timer = window.setTimeout(() => {
        timer = null;
        scan();
      }, 0);
    };

    scan();
    const observer = new MutationObserver(scheduleScan);
    observer.observe(root, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    return () => {
      observer.disconnect();
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [containerRef, scan]);

  useEffect(() => {
    targets.forEach(({ id, block }) => {
      const collapsed = collapsedById[id] ?? true;
      const collapsedValue = String(collapsed);
      if (block.dataset.qwenpawCodeCollapsed !== collapsedValue) {
        block.dataset.qwenpawCodeCollapsed = collapsedValue;
      }
    });
  }, [collapsedById, targets]);

  const toggleCollapsed = useCallback((id: string) => {
    setCollapsedById((current) => ({
      ...current,
      [id]: !(current[id] ?? true),
    }));
  }, []);

  return targets.map(({ id, actions }) => {
    const collapsed = collapsedById[id] ?? true;
    const label = collapsed ? labels.expand : labels.collapse;

    return createPortal(
      <button
        aria-expanded={!collapsed}
        aria-label={label}
        className={styles.codeCollapseToggle}
        title={label}
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          toggleCollapsed(id);
        }}
      >
        {collapsed ? (
          <ChevronDown aria-hidden="true" size={16} />
        ) : (
          <ChevronUp aria-hidden="true" size={16} />
        )}
      </button>,
      actions,
      id,
    );
  });
}

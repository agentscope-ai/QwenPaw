import React, { useCallback, useLayoutEffect, useRef, useState } from "react";
import { Accordion } from "@agentscope-ai/chat";

type AccordionProps = React.ComponentProps<typeof Accordion>;

interface LazyAccordionProps
  extends Omit<AccordionProps, "children" | "defaultOpen" | "open"> {
  className?: string;
  defaultOpen?: boolean;
  renderChildren: () => React.ReactElement;
}

const HEADER_SELECTOR =
  '[class*="-accordion-group-header-open"], [class*="-accordion-group-header-close"]';
const MESSAGE_SCROLL_SELECTOR =
  '[class*="chat-anywhere-message-list-bubble-scroll"]';

/**
 * Adds destroy-on-close semantics to the vendor Accordion.
 *
 * The vendor component always mounts its children and hides them with
 * `height: 0`. Keeping this adapter controlled lets closed process groups
 * avoid rendering reasoning, Markdown, and tool-card subtrees altogether.
 */
export default function LazyAccordion({
  className,
  defaultOpen = false,
  renderChildren,
  ...accordionProps
}: LazyAccordionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const rootRef = useRef<HTMLDivElement>(null);
  const pendingHeaderTopRef = useRef<number | null>(null);
  const pendingScrollerRef = useRef<HTMLElement | null>(null);

  useLayoutEffect(() => {
    const previousTop = pendingHeaderTopRef.current;
    const scroller = pendingScrollerRef.current;
    pendingHeaderTopRef.current = null;
    pendingScrollerRef.current = null;
    if (previousTop === null || !scroller) return;

    const header = rootRef.current?.querySelector(HEADER_SELECTOR);
    if (!header) return;
    const topDelta = header.getBoundingClientRect().top - previousTop;
    if (Math.abs(topDelta) > 0.5) scroller.scrollTop += topDelta;
  }, [open]);

  const handleClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    if (!(event.target instanceof Element)) return;
    const header = event.target.closest(HEADER_SELECTOR);

    // The vendor contract exposes open/close header classes, but its wrapper
    // depth is not stable. Only the first (outer) header controls this group;
    // later headers belong to nested tool/reasoning accordions.
    if (
      !header ||
      header !== event.currentTarget.querySelector(HEADER_SELECTOR)
    )
      return;
    pendingHeaderTopRef.current = header.getBoundingClientRect().top;
    pendingScrollerRef.current = header.closest<HTMLElement>(
      MESSAGE_SCROLL_SELECTOR,
    );
    setOpen((current) => !current);
  }, []);

  return (
    <div ref={rootRef} className={className} onClick={handleClick}>
      <Accordion {...accordionProps} open={open}>
        <>{open ? renderChildren() : null}</>
      </Accordion>
    </div>
  );
}

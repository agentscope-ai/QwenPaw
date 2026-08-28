import React, { useCallback, useState } from "react";
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

  const handleClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    if (!(event.target instanceof Element)) return;
    const header = event.target.closest(HEADER_SELECTOR);

    // The vendor contract exposes open/close header classes, but its wrapper
    // depth is not stable. Only the first (outer) header controls this group;
    // later headers belong to nested tool/reasoning accordions.
    if (header !== event.currentTarget.querySelector(HEADER_SELECTOR)) return;
    setOpen((current) => !current);
  }, []);

  return (
    <div className={className} onClick={handleClick}>
      <Accordion {...accordionProps} open={open}>
        <>{open ? renderChildren() : null}</>
      </Accordion>
    </div>
  );
}

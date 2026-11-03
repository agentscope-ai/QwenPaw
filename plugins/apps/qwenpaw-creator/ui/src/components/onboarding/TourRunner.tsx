import { useEffect, useMemo, useState } from "react";
import { Tour, type TourProps } from "antd";

/**
 * Generic spotlight tour runner: polls until the blueprint's anchors mount,
 * then opens an antd Tour; steps whose anchors are missing are skipped.
 * Shared by the home page and the project workspace.
 */

export interface TourStepBlueprint {
  selectors: string[];
  title: string;
  description: React.ReactNode;
}

export function resolveTarget(selectors: string[]): HTMLElement | null {
  // display:contents anchors report a 0x0 rect, which would pin the antd
  // Tour spotlight to the viewport origin — only accept sized elements and
  // as a last resort spotlight the first sized descendant.
  const sized = (element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  let zeroSize: HTMLElement | null = null;
  for (const selector of selectors) {
    const element = document.querySelector<HTMLElement>(selector);
    if (!element) continue;
    if (sized(element)) return element;
    zeroSize = zeroSize ?? element;
  }
  if (zeroSize) {
    for (const descendant of zeroSize.querySelectorAll<HTMLElement>("*")) {
      if (sized(descendant)) return descendant;
    }
  }
  return null;
}

interface TourRunnerProps {
  steps: TourStepBlueprint[];
  /** Trigger condition (first visit or manual replay); does nothing when false. */
  shouldRun: boolean;
  /** Called on finish (completed or dismissed); persists the completion flag. */
  onFinish: () => void;
}

export default function TourRunner({
  steps,
  shouldRun,
  onFinish,
}: TourRunnerProps) {
  const [open, setOpen] = useState(false);
  const [anchorsReady, setAnchorsReady] = useState(false);
  // Browser zoom / window resize invalidate the measured spotlight rect;
  // bumping the tick rebuilds the steps so antd re-resolves and re-measures.
  const [viewportTick, setViewportTick] = useState(0);
  const active = shouldRun && !open;

  useEffect(() => {
    if (!open) return;
    let raf = 0;
    const remeasure = () => {
      window.cancelAnimationFrame(raf);
      raf = window.requestAnimationFrame(() =>
        setViewportTick((tick) => tick + 1),
      );
    };
    window.addEventListener("resize", remeasure);
    window.visualViewport?.addEventListener("resize", remeasure);
    return () => {
      window.cancelAnimationFrame(raf);
      window.removeEventListener("resize", remeasure);
      window.visualViewport?.removeEventListener("resize", remeasure);
    };
  }, [open]);

  // Anchors may render asynchronously (snapshot polling + lazy loading), so
  // poll until the first anchor mounts.
  useEffect(() => {
    if (!active) return;
    setAnchorsReady(false);
    let tries = 0;
    const timer = window.setInterval(() => {
      tries += 1;
      if (resolveTarget(steps[0].selectors)) {
        window.clearInterval(timer);
        setAnchorsReady(true);
        return;
      }
      // Wait at most 30s; the page can stay in a skeleton state for a long time
      // during the Agent's initial planning.
      if (tries > 100) window.clearInterval(timer);
    }, 300);
    return () => window.clearInterval(timer);
  }, [active, steps]);

  useEffect(() => {
    if (active && anchorsReady) setOpen(true);
  }, [active, anchorsReady]);

  // Leaving the page mid-tour (route change) must dismiss the tour without
  // marking it done, so it re-runs on the next visit instead of showing
  // whichever step still resolves on the new page.
  useEffect(() => {
    if (!shouldRun && open) {
      setOpen(false);
      setAnchorsReady(false);
    }
  }, [shouldRun, open]);

  const tourSteps = useMemo<TourProps["steps"]>(() => {
    if (!open) return [];
    void viewportTick;
    return steps
      .filter((step) => resolveTarget(step.selectors))
      .map((step) => ({
        title: step.title,
        // Long guides (e.g. the English model-setup step) must scroll inside
        // the panel instead of growing taller than the viewport.
        description: (
          <div className="max-h-[min(56vh,480px)] overflow-y-auto overscroll-contain pr-1">
            {step.description}
          </div>
        ),
        target: () => resolveTarget(step.selectors) as HTMLElement,
      }));
  }, [open, steps, viewportTick]);

  const finish = () => {
    setOpen(false);
    setAnchorsReady(false);
    onFinish();
  };

  if (!open || !tourSteps || tourSteps.length === 0) return null;

  return (
    <Tour
      open={open}
      steps={tourSteps}
      scrollIntoViewOptions={{ block: "center", inline: "nearest" }}
      onClose={finish}
      onFinish={finish}
    />
  );
}

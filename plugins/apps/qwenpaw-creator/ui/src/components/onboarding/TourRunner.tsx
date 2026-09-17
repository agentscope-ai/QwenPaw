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
  for (const selector of selectors) {
    const element = document.querySelector<HTMLElement>(selector);
    if (element) return element;
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
  const active = shouldRun && !open;

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

  const tourSteps = useMemo<TourProps["steps"]>(() => {
    if (!open) return [];
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
  }, [open, steps]);

  const finish = () => {
    setOpen(false);
    setAnchorsReady(false);
    onFinish();
  };

  if (!open || !tourSteps || tourSteps.length === 0) return null;

  return (
    <Tour open={open} steps={tourSteps} onClose={finish} onFinish={finish} />
  );
}

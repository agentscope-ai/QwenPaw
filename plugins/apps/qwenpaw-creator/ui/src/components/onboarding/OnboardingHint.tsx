import type { ReactNode } from "react";
import { Lightbulb } from "lucide-react";
import {
  useOnboardingStore,
  type OnboardingHintKey,
} from "@/store/onboardingStore";

interface OnboardingHintProps {
  hintKey: OnboardingHintKey;
  children: ReactNode;
  className?: string;
}

/**
 * One-time contextual hint bar: shown inline the first time a UI element
 * appears; once the user clicks "知道了" (got it) it never shows again
 * (persisted across sessions). An inline bar is used instead of an overlay to
 * avoid positioning drift inside scrollable containers.
 */
export default function OnboardingHint({
  hintKey,
  children,
  className,
}: OnboardingHintProps) {
  const seen = useOnboardingStore((state) => state.hints[hintKey] === true);
  const markHintSeen = useOnboardingStore((state) => state.markHintSeen);
  if (seen) return null;
  return (
    <div
      data-onboarding-hint={hintKey}
      className={`flex items-start gap-1.5 rounded-md border border-[var(--color-accent)]/30 bg-[var(--color-accent-soft)]/50 px-2 py-1.5 text-[11px] leading-4 text-[var(--color-text-secondary)] ${
        className ?? ""
      }`}
    >
      <Lightbulb className="mt-0.5 h-3 w-3 shrink-0 text-[var(--color-accent)]" />
      <span className="min-w-0 flex-1">{children}</span>
      <button
        type="button"
        onClick={() => markHintSeen(hintKey)}
        className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-accent)] transition-colors hover:bg-[var(--color-accent-soft)]"
      >
        知道了
      </button>
    </div>
  );
}

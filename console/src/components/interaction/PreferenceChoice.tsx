import type { ReactNode } from "react";
import { Check } from "lucide-react";
import { InteractiveCard } from "./InteractiveCard";
import { RunningGlow } from "./RunningGlow";
import styles from "./PreferenceChoice.module.less";

/** One explicit choice, with immediate feedback and no implicit save behavior. */
export function PreferenceChoice({
  label,
  description,
  icon,
  selected,
  disabled,
  onSelect,
}: {
  label: ReactNode;
  description?: string;
  icon: ReactNode;
  selected: boolean;
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    <InteractiveCard tilt={1.5} className={styles.surface}>
      <button
        type="button"
        data-press
        className={styles.choice}
        aria-pressed={selected}
        disabled={disabled}
        onClick={onSelect}
      >
        <span className={styles.top}>
          <span className={styles.icon}>{icon}</span>
          <Check size={16} style={{ opacity: selected ? 1 : 0 }} />
        </span>
        <strong>{label}</strong>
        {description && (
          <span className={styles.description}>{description}</span>
        )}
        <RunningGlow active={selected} />
      </button>
    </InteractiveCard>
  );
}

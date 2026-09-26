import { useId, type ReactNode } from "react";
import {
  AnimatePresence,
  LayoutGroup,
  motion,
  useReducedMotion,
} from "motion/react";
import styles from "./PolicySelector.module.less";

type Option<T extends string> = {
  value: T;
  label: string;
  description: string;
  icon?: ReactNode;
  disabled?: boolean;
};

/** A compact choice with an optional persistent behavior explanation. */
export function PolicySelector<T extends string>({
  value,
  options,
  onChange,
  disabled,
  label,
  showDescription = true,
}: {
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  label: string;
  showDescription?: boolean;
}) {
  const id = useId();
  const reduced = useReducedMotion();
  const selected = options.find((option) => option.value === value);
  return (
    <LayoutGroup id={id}>
      <div className={styles.selector}>
        <div className={styles.options} role="radiogroup" aria-label={label}>
          {options.map((option) => (
            <label
              key={option.value}
              className={styles.option}
              data-selected={value === option.value || undefined}
              data-disabled={disabled || option.disabled || undefined}
            >
              <input
                type="radio"
                name={id}
                value={option.value}
                checked={value === option.value}
                disabled={disabled || option.disabled}
                onChange={() => onChange(option.value)}
                aria-describedby={
                  showDescription ? `${id}-description` : undefined
                }
              />
              {value === option.value && (
                <motion.i
                  layoutId="selection"
                  transition={
                    reduced
                      ? { duration: 0 }
                      : { type: "spring", stiffness: 400, damping: 36 }
                  }
                />
              )}
              <span>
                {option.icon}
                {option.label}
              </span>
            </label>
          ))}
        </div>
        {showDescription && (
          <div
            id={`${id}-description`}
            className={styles.description}
            aria-live="polite"
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.p
                key={value}
                initial={{ opacity: 0, y: reduced ? 0 : 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: reduced ? 0 : 0.12 }}
              >
                {selected?.description}
              </motion.p>
            </AnimatePresence>
          </div>
        )}
      </div>
    </LayoutGroup>
  );
}

import { useEffect, useId, useRef, useState } from "react";
import { Brain } from "lucide-react";
import { motion, useInView, useReducedMotion } from "motion/react";
import { useTranslation } from "react-i18next";
import type { ThinkingControlSpec, ThinkingPreference } from "./types";
import styles from "./thinking.module.less";

const wave = "M-24 0Q-18-.8-12 0T0 0T12 0T24 0T36 0T48 0V30H-24Z";

export function ThinkingIndicator({
  control,
  value,
}: {
  control: ThinkingControlSpec;
  value: ThinkingPreference;
}) {
  const { t } = useTranslation();
  const id = useId().replace(/:/g, "");
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref);
  const reduced = useReducedMotion();
  const [visible, setVisible] = useState(!document.hidden);
  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  const active =
    (control.kind === "budget" || control.kind === "effort") &&
    !["off", "inherit"].includes(value.level);
  const efforts = control.efforts.filter(
    (level) => level !== "off" && level !== "inherit",
  );
  const low = control.budget_min ?? 1;
  const high = control.budget_max ?? low;
  const ratio = Math.min(
    1,
    Math.max(
      0,
      value.level === "budget"
        ? high === low
          ? 1
          : ((value.budget_tokens ?? control.budget_default ?? low) - low) /
            (high - low)
        : efforts.length === 1
        ? 1
        : efforts.findIndex((level) => level === value.level) /
          Math.max(1, efforts.length - 1),
    ),
  );
  const band =
    ratio < 0.25
      ? "light"
      : ratio < 0.6
      ? "balanced"
      : ratio < 0.85
      ? "deep"
      : "intensive";
  const state =
    control.kind === "unknown" || control.kind === "unsupported"
      ? control.kind
      : value.level === "budget"
      ? band
      : value.level;
  const label = t(`thinkingControl.${state}`);
  const animate = active && inView && visible && !reduced;
  if (control.kind === "unknown" || control.kind === "unsupported") return null;
  return (
    <span
      ref={ref}
      className={styles.thinkingIndicator}
      title={label}
      data-state={state}
    >
      {!active && (
        <Brain size={18} strokeWidth={1.65} role="img" aria-label={label} />
      )}
      {active && (
        <svg
          viewBox="0 0 24 24"
          width="18"
          height="18"
          role="img"
          aria-label={label}
        >
          <title>{label}</title>
          <defs>
            <mask
              id={`${id}-brain`}
              maskUnits="userSpaceOnUse"
              x="0"
              y="0"
              width="24"
              height="24"
            >
              <Brain width="24" height="24" stroke="white" strokeWidth={1.65} />
            </mask>
            <linearGradient id={`${id}-liquid`} x1="0" y1="0" x2="0.25" y2="1">
              <stop offset="0%" stopColor="#ffd1a3" />
              <stop offset="30%" stopColor="#ffa348" />
              <stop offset="100%" stopColor="#f57808" />
            </linearGradient>
          </defs>
          <Brain
            width="24"
            height="24"
            strokeWidth={1.65}
            opacity={0.5}
            aria-hidden="true"
          />
          <g mask={`url(#${id}-brain)`}>
            <motion.g
              initial={false}
              animate={{ y: 18 - ratio * 17 }}
              transition={
                reduced
                  ? { duration: 0 }
                  : { type: "spring", stiffness: 240, damping: 25 }
              }
            >
              <motion.g
                animate={{ rotate: animate ? [-1.2, 1.2, -1.2] : 0 }}
                transition={
                  animate
                    ? { duration: 3.2, repeat: Infinity, ease: "easeInOut" }
                    : { duration: 0 }
                }
                style={{ transformOrigin: "12px 12px" }}
              >
                <motion.path
                  d={wave}
                  fill={`url(#${id}-liquid)`}
                  opacity={0.28}
                  animate={{ x: animate ? [-24, 0] : 0, y: -0.7 }}
                  transition={
                    animate
                      ? { duration: 3.1, repeat: Infinity, ease: "linear" }
                      : { duration: 0 }
                  }
                />
                <motion.path
                  d={wave}
                  fill={`url(#${id}-liquid)`}
                  animate={{ x: animate ? [0, -24] : 0 }}
                  transition={
                    animate
                      ? { duration: 2.6, repeat: Infinity, ease: "linear" }
                      : { duration: 0 }
                  }
                />
              </motion.g>
            </motion.g>
          </g>
        </svg>
      )}
    </span>
  );
}

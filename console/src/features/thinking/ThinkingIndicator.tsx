import { useEffect, useId, useRef, useState } from "react";
import { Brain } from "lucide-react";
import { motion, useInView, useReducedMotion } from "motion/react";
import { useTranslation } from "react-i18next";
import type { ThinkingControlSpec, ThinkingPreference } from "./types";
import styles from "./thinking.module.less";

// Closed silhouette matching the Lucide Brain outline; its original strokes
// remain on top so the liquid never obscures the folds.
const silhouette =
  "M12 5C12 1 6 1 6 5.125C2.8 5.5 1.5 8.5 3.477 10.895" +
  "C.5 13 1.8 16.9 4.033 17.483C3.5 23 12 24 12 18" +
  "C12 24 20.5 23 19.967 17.483C22.2 16.9 23.5 13 20.523 10.895" +
  "C22.5 8.5 21.2 5.5 18 5.125C18 1 12 1 12 5Z";
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
  const label = t(
    `thinkingControl.${value.level === "budget" ? band : value.level}`,
  );
  const animate = active && inView && visible && !reduced;
  return (
    <span ref={ref} className={styles.thinkingIndicator}>
      {active && (
        <svg
          viewBox="0 0 24 24"
          width="20"
          height="20"
          role="img"
          aria-label={label}
        >
          <title>{label}</title>
          <defs>
            <clipPath id={`${id}-brain`}>
              <path d={silhouette} />
            </clipPath>
            <linearGradient id={`${id}-liquid`} x1="0" y1="0" x2="0.25" y2="1">
              <stop offset="0%" stopColor="#ffd1a3" />
              <stop offset="30%" stopColor="#ffa348" />
              <stop offset="100%" stopColor="#f57808" />
            </linearGradient>
            <linearGradient
              id={`${id}-outline`}
              gradientUnits="userSpaceOnUse"
              x1="2"
              y1="2"
              x2="18"
              y2="22"
            >
              <stop offset="0%" stopColor="var(--brain-edge-light)" />
              <stop offset="100%" stopColor="var(--brain-edge-dark)" />
            </linearGradient>
          </defs>
          <g clipPath={`url(#${id}-brain)`}>
            <path d={silhouette} fill={`url(#${id}-liquid)`} opacity={0.08} />
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
          <Brain
            width="24"
            height="24"
            strokeWidth={1.4}
            stroke={`url(#${id}-outline)`}
            aria-hidden="true"
          />
        </svg>
      )}
    </span>
  );
}

import React from "react";
import { useLoopStore, type BudgetLevel } from "../../stores/loopStore";
import styles from "./index.module.less";

const BUDGET_OPTIONS: { level: BudgetLevel; label: string; dots: number }[] = [
  { level: "low", label: "Low", dots: 1 },
  { level: "medium", label: "Med", dots: 2 },
  { level: "high", label: "High", dots: 3 },
];

const DOT_COLORS: Record<BudgetLevel, string> = {
  low: "#22c55e",
  medium: "#eab308",
  high: "#f97316",
};

/**
 * Budget selector (Low/Med/High) shown in the sender bottom bar when a
 * loop chip is active. Visual dots indicate budget intensity.
 */
export const LoopBudgetSelector: React.FC = () => {
  const { selectedSkill, budgetLevel, setBudgetLevel } = useLoopStore();

  if (!selectedSkill) return null;

  return (
    <div className={styles.budgetSelector}>
      {BUDGET_OPTIONS.map(({ level, label, dots }) => {
        const isActive = budgetLevel === level;
        const cls = [
          styles.budgetOption,
          isActive ? styles.budgetOptionActive : "",
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <div
            key={level}
            className={cls}
            onClick={() => setBudgetLevel(level)}
          >
            <div className={styles.budgetDots}>
              {[1, 2, 3].map((i) => (
                <span
                  key={i}
                  className={styles.budgetDot}
                  style={
                    isActive && i <= dots
                      ? { background: DOT_COLORS[level] }
                      : undefined
                  }
                />
              ))}
            </div>
            <span>{label}</span>
          </div>
        );
      })}
    </div>
  );
};

import React from "react";
import { useTranslation } from "react-i18next";
import { useLoopStore, type BudgetLevel } from "../../stores/loopStore";
import styles from "./index.module.less";

const BUDGET_LEVELS: { level: BudgetLevel; i18nKey: string; dots: number }[] = [
  { level: "low", i18nKey: "loop.budget.low", dots: 1 },
  { level: "medium", i18nKey: "loop.budget.medium", dots: 2 },
  { level: "high", i18nKey: "loop.budget.high", dots: 3 },
];

const DOT_COLORS: Record<BudgetLevel, string> = {
  low: "var(--ant-color-success, #52c41a)",
  medium: "var(--ant-color-warning, #faad14)",
  high: "var(--ant-color-warning-border, #ffa940)",
};

const NO_BUDGET_SKILLS = new Set(["mission"]);

export const LoopBudgetSelector: React.FC = () => {
  const { t } = useTranslation();
  const { selectedSkill, budgetLevel, setBudgetLevel } = useLoopStore();

  if (!selectedSkill || NO_BUDGET_SKILLS.has(selectedSkill.name)) return null;

  return (
    <div className={styles.budgetSelector}>
      {BUDGET_LEVELS.map(({ level, i18nKey, dots }) => {
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
            <span>{t(i18nKey)}</span>
          </div>
        );
      })}
    </div>
  );
};

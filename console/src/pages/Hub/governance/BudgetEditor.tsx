import { useTranslation } from "react-i18next";
import { InputNumber, Select } from "antd";
import styles from "./governance.module.less";

import type { BudgetMode } from "./budgetUtils";
export default function BudgetEditor({
  mode,
  amount,
  onMode,
  onAmount,
  allowInherit = false,
}: {
  mode: BudgetMode;
  amount: number | null;
  onMode: (mode: BudgetMode) => void;
  onAmount: (value: number | null) => void;
  allowInherit?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.budgetEditor}>
      <Select<BudgetMode>
        value={mode}
        onChange={onMode}
        aria-label={t("hub.governance.budget.monthlyLimit")}
        style={{ width: "100%", maxWidth: 360 }}
        options={[
          ...(allowInherit
            ? [
                {
                  value: "inherit" as const,
                  label: t("hub.governance.budget.inherit"),
                },
              ]
            : []),
          { value: "unlimited", label: t("hub.governance.budget.unlimited") },
          { value: "limited", label: t("hub.governance.budget.custom") },
          { value: "blocked", label: t("hub.governance.budget.pause") },
        ]}
      />
      {mode === "limited" && (
        <InputNumber
          style={{ width: "100%", maxWidth: 360 }}
          aria-label={t("hub.governance.budget.monthlyLimit")}
          min={1}
          precision={0}
          value={amount}
          onChange={onAmount}
          suffix={t("hub.governance.budget.perMonth")}
          placeholder="1,000,000"
        />
      )}
    </div>
  );
}

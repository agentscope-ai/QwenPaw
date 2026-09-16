import { useTranslation } from "react-i18next";
import { InputNumber, Radio } from "antd";
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
      <Radio.Group
        value={mode}
        onChange={(e) => onMode(e.target.value)}
        className={styles.choices}
      >
        {allowInherit && (
          <Radio value="inherit">{t("hub.governance.budget.inherit")}</Radio>
        )}
        <Radio value="limited">{t("hub.governance.budget.custom")}</Radio>
        <Radio value="unlimited">{t("hub.governance.budget.unlimited")}</Radio>
        <Radio value="blocked">{t("hub.governance.budget.pause")}</Radio>
      </Radio.Group>
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

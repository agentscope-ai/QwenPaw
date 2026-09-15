import { InputNumber, Radio } from "antd";
import { useGovernanceText } from "./shared";
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
  const text = useGovernanceText();
  return (
    <div className={styles.budgetEditor}>
      <Radio.Group
        value={mode}
        onChange={(e) => onMode(e.target.value)}
        className={styles.choices}
      >
        {allowInherit && (
          <Radio value="inherit">
            {text("继承组织默认", "Organization default")}
          </Radio>
        )}
        <Radio value="limited">{text("自定义额度", "Custom limit")}</Radio>
        <Radio value="unlimited">{text("不限额", "Unlimited")}</Radio>
        <Radio value="blocked">{text("暂停调用", "Pause calls")}</Radio>
      </Radio.Group>
      {mode === "limited" && (
        <InputNumber
          style={{ width: "100%", maxWidth: 360 }}
          aria-label={text("每月 Token 额度", "Monthly token limit")}
          min={1}
          precision={0}
          value={amount}
          onChange={onAmount}
          suffix={text("Token / 月", "Token / month")}
          placeholder="1,000,000"
        />
      )}
    </div>
  );
}

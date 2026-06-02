import { Button } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { InstallTarget } from "../useMarketInstall";
import styles from "./TargetToggle.module.less";

interface TargetToggleProps {
  target: InstallTarget;
  onChange: (next: InstallTarget) => void;
  size?: "small" | "middle" | "large";
}

export function TargetToggle({ target, onChange, size }: TargetToggleProps) {
  const { t } = useTranslation();
  return (
    <div className={styles.targetToggle}>
      <Button
        size={size}
        type={target === "pool" ? "primary" : "default"}
        onClick={() => onChange("pool")}
      >
        {t("market.targetPool")}
      </Button>
      <Button
        size={size}
        type={target === "workspace" ? "primary" : "default"}
        onClick={() => onChange("workspace")}
      >
        {t("market.targetWorkspace")}
      </Button>
    </div>
  );
}

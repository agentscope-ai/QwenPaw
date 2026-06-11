import { Button } from "@/components/ui/button";
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
        size={size === "small" ? "sm" : size === "large" ? "lg" : "default"}
        variant={target === "pool" ? "default" : "outline"}
        onClick={() => onChange("pool")}
      >
        {t("market.targetPool")}
      </Button>
      <Button
        size={size === "small" ? "sm" : size === "large" ? "lg" : "default"}
        variant={target === "workspace" ? "default" : "outline"}
        onClick={() => onChange("workspace")}
      >
        {t("market.targetWorkspace")}
      </Button>
    </div>
  );
}

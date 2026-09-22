import type { ReactNode } from "react";
import { Tooltip } from "antd";
import { CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

export default function InlineHelp({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <Tooltip title={children} trigger={["hover", "focus", "click"]}>
      <button
        type="button"
        className={styles.help}
        aria-label={t("common.help")}
      >
        <CircleHelp size={15} strokeWidth={1.7} aria-hidden />
      </button>
    </Tooltip>
  );
}

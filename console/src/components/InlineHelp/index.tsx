import { useState, type ReactNode } from "react";
import { Tooltip } from "antd";
import { CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

export default function InlineHelp({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <Tooltip
      title={children}
      open={open}
      onOpenChange={setOpen}
      trigger={["hover", "focus"]}
    >
      <button
        type="button"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
        className={styles.help}
        aria-label={t("common.help")}
      >
        <CircleHelp size={15} strokeWidth={1.7} aria-hidden />
      </button>
    </Tooltip>
  );
}

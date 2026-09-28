import { useState, type ReactNode } from "react";
import { Tooltip } from "antd";
import { CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

export default function InlineHelp({
  children,
  inline = false,
  subject,
}: {
  children: ReactNode;
  inline?: boolean;
  subject?: string;
}) {
  const Trigger = inline ? "span" : "button";
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <Tooltip
      title={children}
      open={open}
      onOpenChange={setOpen}
      trigger={["hover", "focus"]}
    >
      <Trigger
        type={inline ? undefined : "button"}
        role={inline ? "button" : undefined}
        tabIndex={inline ? 0 : undefined}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (inline && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            event.stopPropagation();
            setOpen(true);
          }
          if (event.key === "Escape" && open) {
            event.preventDefault();
            event.stopPropagation();
            setOpen(false);
          }
        }}
        className={styles.help}
        aria-label={
          subject
            ? `${subject} · ${t("common.help")}`
            : typeof children === "string"
            ? children
            : t("common.help")
        }
      >
        <CircleHelp size={15} strokeWidth={1.7} aria-hidden />
      </Trigger>
    </Tooltip>
  );
}

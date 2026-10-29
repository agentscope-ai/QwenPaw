import { Button, Tooltip, type ButtonProps } from "antd";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import styles from "./IconButton.module.less";

type IconButtonProps = Omit<ButtonProps, "aria-label" | "children" | "icon"> & {
  icon: LucideIcon;
  label: string;
  tooltip?: ReactNode;
};

/** A named Lucide-only action with the shared desktop and touch hit target. */
export function IconButton({
  icon: Icon,
  label,
  tooltip = label,
  className = "",
  disabled = false,
  loading = false,
  ...props
}: IconButtonProps) {
  const busy = !!loading;
  return (
    <Tooltip title={tooltip}>
      <Button
        {...props}
        aria-label={label}
        aria-busy={busy || undefined}
        className={`${styles.button} ${className}`}
        data-icon-button
        disabled={disabled || busy}
        icon={<Icon aria-hidden="true" size={16} strokeWidth={1.875} />}
        loading={loading}
      />
    </Tooltip>
  );
}

import styles from "./SettingsField.module.less";
import type { ComponentProps, ReactNode } from "react";
import { Form } from "@agentscope-ai/design";
import InlineHelp from "@/components/InlineHelp";

/** Form labels share keyboard- and touch-accessible contextual help. */
export function SettingsField({
  label,
  tooltip,
  className,
  ...props
}: Omit<ComponentProps<typeof Form.Item>, "tooltip"> & {
  tooltip?: ReactNode;
}) {
  return (
    <Form.Item
      {...props}
      className={`${className ?? ""} ${
        props.valuePropName === "checked" ? styles.toggle : ""
      }`}
      label={
        tooltip && label ? (
          <span
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            {label}
            <InlineHelp
              inline
              subject={typeof label === "string" ? label : undefined}
            >
              {tooltip}
            </InlineHelp>
          </span>
        ) : (
          label
        )
      }
    />
  );
}

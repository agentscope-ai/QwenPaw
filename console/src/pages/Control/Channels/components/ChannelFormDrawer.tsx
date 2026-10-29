import { Form } from "@agentscope-ai/design";
import { useLayoutEffect, useMemo, useRef } from "react";
import type { ComponentProps } from "react";
import { ChannelDrawer } from "./ChannelDrawer";
import { normalizeChannelSubmitValues } from "./channelConfig";

const SENSITIVE_FIELDS = [
  "client_secret",
  "app_secret",
  "bot_token",
  "password",
  "access_token",
  "app_token",
  "secret",
  "sk",
  "api_key",
  "twilio_auth_token",
  "livekit_api_secret",
  "sip_password",
] as const;

function normalizeChannelFormValues(
  values: Record<string, unknown> | undefined,
): Record<string, unknown> {
  const clearedSecrets = Object.fromEntries(
    SENSITIVE_FIELDS.map((field) => [field, undefined]),
  );
  return {
    ...clearedSecrets,
    enabled: false,
    bot_prefix: "",
    show_tool_calls: true,
    show_tool_results: true,
    tool_call_max_length: 200,
    tool_result_max_length: 500,
    show_thinking: true,
    ...values,
    access_control_dm:
      Boolean(values?.access_control_dm) || values?.dm_policy === "allowlist",
    access_control_group:
      Boolean(values?.access_control_group) ||
      values?.group_policy === "allowlist",
  };
}

type Props = Omit<
  ComponentProps<typeof ChannelDrawer>,
  "form" | "initialValues"
> & {
  ownerKey: string;
  initialValues: Record<string, unknown> | undefined;
};

export function ChannelFormDrawer({
  ownerKey,
  initialValues,
  open,
  activeKey,
  onSubmit,
  ...props
}: Props) {
  const [form] = Form.useForm<Record<string, unknown>>();
  const normalizedValues = useMemo(
    () => normalizeChannelFormValues(initialValues),
    [initialValues],
  );
  const previous = useRef<{
    ownerKey: string;
    open: boolean;
    values: Record<string, unknown>;
  }>();

  useLayoutEffect(() => {
    const previousSession = previous.current;
    const initialize =
      !open || !previousSession?.open || previousSession.ownerKey !== ownerKey;
    if (initialize) form.resetFields();
    if (open) {
      const names = new Set([
        ...Object.keys(previousSession?.values ?? {}),
        ...Object.keys(normalizedValues),
      ]);
      // Save acknowledgements may arrive after a newer, even invalid edit.
      // Sync clean fields and acknowledge matching drafts without resetting.
      form.setFields(
        Array.from(names)
          .filter(
            (name) =>
              initialize ||
              !form.isFieldTouched(name) ||
              JSON.stringify(form.getFieldValue(name)) ===
                JSON.stringify(normalizedValues[name]),
          )
          .map((name) => ({
            name,
            value: normalizedValues[name],
            touched: false,
          })),
      );
    }
    previous.current = { ownerKey, open, values: normalizedValues };
  }, [form, normalizedValues, open, ownerKey]);

  return (
    <ChannelDrawer
      {...props}
      open={open}
      activeKey={activeKey}
      form={form}
      initialValues={normalizedValues}
      onSubmit={(values) =>
        onSubmit(normalizeChannelSubmitValues(activeKey, values))
      }
    />
  );
}

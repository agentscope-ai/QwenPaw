import { Form } from "@agentscope-ai/design";
import { useLayoutEffect, useMemo } from "react";
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
) {
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

  useLayoutEffect(() => {
    form.resetFields();
    if (open) form.setFieldsValue(normalizedValues);
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

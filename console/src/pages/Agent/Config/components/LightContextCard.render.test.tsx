import { useEffect } from "react";
import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Form } from "@agentscope-ai/design";
import type { FormInstance } from "antd";
import { renderWithProviders } from "@/test/common_setup";
import { LightContextCard } from "./LightContextCard";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback || _key,
  }),
}));

function ContextForm({ onForm }: { onForm: (form: FormInstance) => void }) {
  const [form] = Form.useForm();
  useEffect(() => {
    onForm(form);
  }, [form, onForm]);
  return (
    <Form
      form={form}
      initialValues={{
        light_context_config: {
          strategy: "scroll",
          token_count_estimate_divisor: 4,
          context_compact_config: {
            enabled: true,
            compact_threshold_ratio: 0.8,
            reserve_threshold_ratio: 0.1,
          },
          scroll_config: { history_retention_days: 30 },
        },
      }}
    >
      <LightContextCard maxInputLength={128_000} />
    </Form>
  );
}

describe("LightContextCard validation", () => {
  it("rejects compact and reserve ratios outside the backend ranges", async () => {
    let form!: FormInstance;
    renderWithProviders(<ContextForm onForm={(value) => (form = value)} />);
    fireEvent.click(
      screen.getByText("agentConfig.contextCompactCollapseLabel"),
    );

    form.setFieldValue(
      [
        "light_context_config",
        "context_compact_config",
        "compact_threshold_ratio",
      ],
      0.95,
    );
    form.setFieldValue(
      [
        "light_context_config",
        "context_compact_config",
        "reserve_threshold_ratio",
      ],
      0,
    );

    await expect(
      form.validateFields([
        [
          "light_context_config",
          "context_compact_config",
          "compact_threshold_ratio",
        ],
        [
          "light_context_config",
          "context_compact_config",
          "reserve_threshold_ratio",
        ],
      ]),
    ).rejects.toMatchObject({ errorFields: expect.any(Array) });
  });
});

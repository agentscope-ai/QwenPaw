import { describe, expect, it, vi } from "vitest";
import { Form } from "@agentscope-ai/design";
import type { FormInstance } from "antd";
import { renderWithProviders } from "@/test/common_setup";
import { LlmRateLimiterCard } from "./LlmRateLimiterCard";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback || _key,
  }),
}));

function RateLimitForm({ onForm }: { onForm: (form: FormInstance) => void }) {
  const [form] = Form.useForm();
  onForm(form);
  return (
    <Form
      form={form}
      initialValues={{
        llm_max_concurrent: 1,
        llm_max_qpm: 0,
        llm_rate_limit_pause: 60,
        llm_rate_limit_jitter: 10,
        llm_acquire_timeout: 10,
      }}
    >
      <LlmRateLimiterCard />
    </Form>
  );
}

describe("LlmRateLimiterCard", () => {
  it("accepts the backend-valid minimum acquire timeout independently of pause and jitter", async () => {
    let form!: FormInstance;
    renderWithProviders(<RateLimitForm onForm={(value) => (form = value)} />);

    await expect(
      form.validateFields(["llm_acquire_timeout"]),
    ).resolves.toBeDefined();
  });
});

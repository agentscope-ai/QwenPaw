import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";
import { Form } from "@agentscope-ai/design";
import type { FormInstance } from "antd";
import { renderWithProviders } from "@/test/common_setup";
import { LlmRetryCard } from "./LlmRetryCard";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback || _key,
  }),
}));

function RetryForm({ onForm }: { onForm: (form: FormInstance) => void }) {
  const [form] = Form.useForm();
  useEffect(() => {
    onForm(form);
  }, [form, onForm]);
  return (
    <Form
      form={form}
      initialValues={{
        llm_retry_enabled: true,
        llm_max_retries: 1,
        llm_backoff_base: 2,
        llm_backoff_cap: 1,
      }}
    >
      <LlmRetryCard />
    </Form>
  );
}

describe("LlmRetryCard", () => {
  it("rejects a backoff cap below the base delay", async () => {
    let form!: FormInstance;
    renderWithProviders(<RetryForm onForm={(value) => (form = value)} />);

    await expect(
      form.validateFields(["llm_backoff_cap"]),
    ).rejects.toMatchObject({
      errorFields: expect.arrayContaining([
        expect.objectContaining({ name: ["llm_backoff_cap"] }),
      ]),
    });
  });
});

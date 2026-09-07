import { Form } from "@agentscope-ai/design";
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import { PowerContextConfigCard } from "./PowerContextConfigCard";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

let formInstance: ReturnType<typeof Form.useForm>[0];

function PowerContextForm() {
  const [form] = Form.useForm();
  formInstance = form;
  return (
    <Form form={form}>
      <PowerContextConfigCard />
    </Form>
  );
}

describe("PowerContextConfigCard", () => {
  it("leaves the scope empty for the per-agent default", () => {
    renderWithProviders(<PowerContextForm />);

    const scope = screen.getByRole("textbox", {
      name: "agentConfig.powercontextConfig.scopeId",
    });
    expect(scope).toHaveValue("");
    expect(scope).toHaveAttribute("maxlength", "256");
    expect(scope).toHaveAttribute(
      "placeholder",
      "agentConfig.powercontextConfig.scopeIdPlaceholder",
    );
  });

  it("rejects a timeout outside the server contract", async () => {
    renderWithProviders(<PowerContextForm />);
    formInstance.setFieldsValue({
      powercontext_memory_config: { timeout: 61 },
    });
    await expect(formInstance.validateFields()).rejects.toBeDefined();
  });

  it("requires a valid PowerContext server URL", async () => {
    renderWithProviders(<PowerContextForm />);
    formInstance.setFieldsValue({
      powercontext_memory_config: { base_url: "not-a-url" },
    });
    await expect(formInstance.validateFields()).rejects.toBeDefined();
  });

  it("rejects an empty PowerContext server URL", async () => {
    renderWithProviders(<PowerContextForm />);
    formInstance.setFieldsValue({
      powercontext_memory_config: { base_url: "" },
    });
    await expect(formInstance.validateFields()).rejects.toBeDefined();
  });

  it("rejects an injected-context budget outside the server contract", async () => {
    renderWithProviders(<PowerContextForm />);
    formInstance.setFieldsValue({
      powercontext_memory_config: {
        auto_memory_search_config: { max_context_bytes: 32769 },
      },
    });
    await expect(formInstance.validateFields()).rejects.toBeDefined();
  });
});

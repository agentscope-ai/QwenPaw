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

function PowerContextForm() {
  const [form] = Form.useForm();
  return (
    <Form form={form}>
      <PowerContextConfigCard />
    </Form>
  );
}

describe("PowerContextConfigCard", () => {
  it("leaves the scope empty for the per-agent default and bounds input", () => {
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
});

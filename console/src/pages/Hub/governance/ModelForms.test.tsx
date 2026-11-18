import { render, screen } from "@testing-library/react";
import { Form } from "antd";
import { describe, expect, it, vi } from "vitest";
import { ConnectionFields } from "./ModelForms";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../Settings/Models/components/ProviderIconComponent", () => ({
  ProviderIcon: () => null,
}));

function renderConnection(providerId: string) {
  return render(
    <Form initialValues={{ provider_id: providerId }}>
      <ConnectionFields
        connections={[]}
        independentScope="organization"
        presets={[
          {
            id: "anthropic",
            name: "Anthropic",
            protocol: "anthropic",
            base_url: "https://api.anthropic.com",
            api_key_prefix: "sk-ant-",
            freeze_url: true,
            base_url_options: [],
            models: [],
          },
        ]}
      />
    </Form>,
  );
}

describe("Hub connection protocol", () => {
  it("does not ask for a protocol for a built-in provider", () => {
    renderConnection("anthropic");
    expect(screen.queryByLabelText("models.protocol")).not.toBeInTheDocument();
  });

  it("lets a custom endpoint select its protocol", () => {
    renderConnection("");
    expect(screen.getByLabelText("models.protocol")).toBeInTheDocument();
    expect(screen.getByText("Chat Completions")).toBeInTheDocument();
  });
});

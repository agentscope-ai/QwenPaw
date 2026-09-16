import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { ReadOnlyConfigSummary } from "./ReadOnlyConfigSummary";

describe("ReadOnlyConfigSummary", () => {
  it("shows safe Agent fields without editable controls", () => {
    render(
      <ReadOnlyConfigSummary
        summary={{
          agent_id: "shared-agent",
          name: "Shared Agent",
          language: "zh",
          timezone: "Asia/Shanghai",
          active_model: { provider_id: "provider-1", model: "model-1" },
          model_switchable: true,
          access_role: "user",
          can_edit: false,
          read_only_reason: "仅使用权限",
        }}
      />,
    );

    expect(screen.getByText("Shared Agent")).toBeInTheDocument();
    expect(screen.getByText("model-1")).toBeInTheDocument();
    expect(screen.getByText("provider-1")).toBeInTheDocument();
    expect(screen.getByText("Asia/Shanghai")).toBeInTheDocument();
    expect(screen.getByText("zh")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});

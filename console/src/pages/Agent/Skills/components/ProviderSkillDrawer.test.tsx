import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProviderSkillDrawer } from "./ProviderSkillDrawer";

vi.mock("@agentscope-ai/design", async () => {
  const React = await import("react");
  return {
    Button: ({
      children,
      ...props
    }: React.ButtonHTMLAttributes<HTMLButtonElement>) =>
      React.createElement("button", props, children),
    Drawer: ({
      children,
      footer,
      open,
      title,
    }: {
      children: React.ReactNode;
      footer: React.ReactNode;
      open: boolean;
      title: React.ReactNode;
    }) =>
      open
        ? React.createElement(
            "section",
            null,
            React.createElement("h1", null, title),
            children,
            footer,
          )
        : null,
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("ProviderSkillDrawer", () => {
  it("shows complete read-only Provider Skill details", () => {
    const skill = {
      name: "openai-templates:artifact-template-analysis-dashboard",
      description: "A complete Provider-owned Skill description.",
      provider_id: "codex",
      source: "plugin",
      enabled: true,
      read_only: true,
      scope: "provider" as const,
    };

    render(<ProviderSkillDrawer open skill={skill} onClose={vi.fn()} />);

    expect(screen.getByText(skill.name)).toBeInTheDocument();
    expect(screen.getByText(skill.description)).toBeInTheDocument();
    expect(screen.getByText("codex")).toBeInTheDocument();
    expect(screen.getByText("plugin")).toBeInTheDocument();
    expect(screen.getByText("skills.readOnly")).toBeInTheDocument();
    expect(screen.queryByText("common.save")).not.toBeInTheDocument();
    expect(screen.queryByText("common.edit")).not.toBeInTheDocument();
  });
});

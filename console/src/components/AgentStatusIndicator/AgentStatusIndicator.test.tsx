import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentStatusIndicator } from "./index";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("AgentStatusIndicator", () => {
  it.each([
    ["disabled", "agent.status.disabled"],
    ["pending", "agent.status.pending"],
    ["starting", "agent.status.starting"],
    ["running", "agent.status.running"],
    ["failed", "agent.status.failed"],
  ] as const)("renders %s status", (status, label) => {
    render(<AgentStatusIndicator status={status} />);
    const indicator = screen.getByRole("status", { name: label });
    expect(indicator).toHaveAttribute("data-status", status);
  });
});

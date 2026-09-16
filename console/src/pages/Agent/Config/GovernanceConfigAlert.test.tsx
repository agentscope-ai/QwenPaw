import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GovernanceConfigAlert } from "./GovernanceConfigAlert";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, string>) =>
      values ? `${key}:${JSON.stringify(values)}` : key,
  }),
}));

describe("GovernanceConfigAlert", () => {
  it("keeps the managed agent and owner visible", () => {
    render(
      <GovernanceConfigAlert
        agentName="Managed Agent"
        agentId="managed-agent"
        ownerUserId="owner-2"
      />,
    );

    expect(screen.getByText("agentConfig.governanceBadge")).toBeVisible();
    expect(screen.getByText("agentConfig.governanceTitle")).toBeVisible();
    expect(screen.getByText(/managed-agent/)).toBeVisible();
    expect(screen.getByText(/owner-2/)).toBeVisible();
  });
});

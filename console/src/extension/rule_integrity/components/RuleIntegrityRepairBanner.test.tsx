import { render, screen, act } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "@/i18n";
import { RuleIntegrityRepairBanner } from "./RuleIntegrityRepairBanner";
import type { ToolGuardRulesIntegrity } from "../api/client";

const RED_TEXT =
  "Security configuration was tampered with; all rules are disabled and auto-repair is in progress";
const GREEN_TEXT =
  "Auto-repair completed. Tool restrictions have been lifted.";

function renderBanner(rulesIntegrity: ToolGuardRulesIntegrity | null) {
  return render(
    <I18nextProvider i18n={i18n}>
      <RuleIntegrityRepairBanner rulesIntegrity={rulesIntegrity} />
    </I18nextProvider>,
  );
}

const tamperedState: ToolGuardRulesIntegrity = {
  ok: false,
  status: "tampered",
  message: "tampered",
  findings: [],
  rules_disabled: true,
  auto_repair_in_progress: true,
};

const repairedState: ToolGuardRulesIntegrity = {
  ok: true,
  status: "ok",
  message: "ok",
  findings: [],
  rules_disabled: false,
  auto_repair_completed: true,
};

describe("RuleIntegrityRepairBanner", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows red auto-repair banner when rules are disabled", () => {
    renderBanner(tamperedState);
    expect(screen.getByText(RED_TEXT)).toBeInTheDocument();
  });

  it("shows green success banner after auto-repair when no prior red session", () => {
    renderBanner(repairedState);
    expect(screen.getByText(GREEN_TEXT)).toBeInTheDocument();
  });

  it("shows timeout retry banner when retry count is present", () => {
    renderBanner({
      ...tamperedState,
      auto_repair_timeout_retry: 2,
      auto_repair_timeout_max: 5,
    });
    expect(
      screen.getByText(
        "Connection timed out. Retrying auto-repair (attempt 2/5)",
      ),
    ).toBeInTheDocument();
  });

  it("shows abandoned banner after max timeout retries", () => {
    renderBanner({
      ...tamperedState,
      auto_repair_in_progress: false,
      auto_repair_abandoned: true,
      auto_repair_timeout_retry: 5,
      auto_repair_timeout_max: 5,
    });
    expect(
      screen.getByText(
        "Connection timed out. Auto-repair was abandoned after 5 failed attempts",
      ),
    ).toBeInTheDocument();
  });

  it("keeps red banner for at least 5 seconds before showing green", async () => {
    vi.useFakeTimers();

    const { rerender } = renderBanner(tamperedState);
    expect(screen.getByText(RED_TEXT)).toBeInTheDocument();

    rerender(
      <I18nextProvider i18n={i18n}>
        <RuleIntegrityRepairBanner rulesIntegrity={repairedState} />
      </I18nextProvider>,
    );

    expect(screen.getByText(RED_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(GREEN_TEXT)).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4999);
    });
    expect(screen.getByText(RED_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(GREEN_TEXT)).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(screen.getByText(GREEN_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(RED_TEXT)).not.toBeInTheDocument();
  });
});

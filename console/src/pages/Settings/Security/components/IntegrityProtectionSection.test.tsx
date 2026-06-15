import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import { IntegrityProtectionSection } from "./IntegrityProtectionSection";
import type {
  IntegrityProtectionSettings,
  FileBaselineProtectionAlert,
  FileBaselineProtectionSettings,
} from "@/api/modules/security";

const {
  mockGetFileBaselineSettings,
  mockGetPersonaAlerts,
  mockGetIntegritySettings,
  mockUpdateFileBaselineSettings,
  mockRestorePersonaAlert,
  mockAcceptPersonaAlert,
} = vi.hoisted(() => ({
  mockGetFileBaselineSettings: vi.fn(),
  mockGetPersonaAlerts: vi.fn(),
  mockGetIntegritySettings: vi.fn(),
  mockUpdateFileBaselineSettings: vi.fn(),
  mockRestorePersonaAlert: vi.fn(),
  mockAcceptPersonaAlert: vi.fn(),
}));

vi.mock("@extension/file_baseline/lib/alertActions", () => ({
  restoreFileBaselineAlert: (...args: unknown[]) => mockRestorePersonaAlert(...args),
  acceptFileBaselineAlert: (...args: unknown[]) => mockAcceptPersonaAlert(...args),
}));

vi.mock("../../../../api", () => ({
  default: {
    getFileBaselineProtectionSettings: mockGetFileBaselineSettings,
    getFileBaselineProtectionAlerts: mockGetPersonaAlerts,
    getIntegrityProtectionSettings: mockGetIntegritySettings,
    updateFileBaselineProtectionSettings: mockUpdateFileBaselineSettings,
    checkIntegrityRuleEntry: vi.fn(),
  },
}));

vi.mock("@extension/file_baseline/hooks/useFileBaselineDriftWatch", () => ({
  useFileBaselineDriftWatch: vi.fn(),
}));

vi.mock("@agentscope-ai/design", async () => {
  const antd = await import("antd");
  return {
    Button: antd.Button,
    Card: antd.Card,
    Dropdown: antd.Dropdown,
    Input: antd.Input,
    Switch: antd.Switch,
    Tooltip: antd.Tooltip,
    Table: antd.Table,
    Tag: antd.Tag,
    Form: antd.Form,
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const labels: Record<string, string> = {
        "security.integrityProtection.fileBaselineProtection":
          "File Baseline Protection",
        "security.integrityProtection.protectedPathsLabel": "Protected paths",
        "security.integrityProtection.defaultOffNotice": "Default off notice",
        "security.integrityProtection.fileBaselineAlertsTitle": "Open baseline drift alerts",
        "security.integrityProtection.fileBaselineAlertsEmpty": "No open baseline drift alerts",
        "security.integrityProtection.protectedFilesDesc": "Toggle per file",
        "security.integrityProtection.fileBaselineToggleTooltip": "Toggle file baseline",
        "security.integrityProtection.pathDescriptions.soul": "Persona",
        "security.integrityProtection.pathPresets.agents": "AGENTS.md",
        "security.integrityProtection.pathDescriptions.agents": "Agent rules",
        "security.integrityProtection.columns.file": "File",
        "security.integrityProtection.columns.reason": "Reason",
        "security.integrityProtection.columns.detail": "Detail",
        "security.integrityProtection.columns.actions": "Actions",
        "security.integrityProtection.restoreAction": "Restore",
        "security.integrityProtection.acceptAction": "Accept",
        "security.integrityProtection.ruleIntegrityTitle": "Rule integrity",
        "security.integrityProtection.ruleIntegrityAction": "Check rules",
        "security.integrityProtection.emptyFindings": "No findings",
        "security.integrityProtection.fileBaselineEnableSuccess": "Persona enabled",
        "security.integrityProtection.fileBaselineDisableSuccess": "Persona disabled",
        "security.integrityProtection.loadFailed": "Load failed",
        "security.integrityProtection.fileBaselineReviewPrompt": "Enter confirmation phrase",
        "security.integrityProtection.confirmFileBaselineRestorePhrase":
          "Confirm file baseline restore",
        "security.integrityProtection.confirmFileBaselineAcceptPhrase":
          "Confirm file baseline accept",
        "security.integrityProtection.restoreSuccess": "Restored",
        "security.integrityProtection.fileBaselineReviewPhraseMismatch":
          "Phrase mismatch",
        "common.confirm": "Confirm",
        "common.cancel": "Cancel",
      };
      return labels[key] ?? key;
    },
  }),
}));

const disabledPersona: FileBaselineProtectionSettings = {
  enabled: false,
  pilot_mode: true,
  protected_targets: ["SOUL.md"],
  protected_paths: [],
  baseline_established: false,
  baseline_cleared_at: null,
  open_alert_count: 0,
};

const enabledPersona: FileBaselineProtectionSettings = {
  ...disabledPersona,
  enabled: true,
  protected_paths: ["SOUL.md"],
  baseline_established: true,
};

const integritySettings: IntegrityProtectionSettings = {
  file_baseline_enabled: false,
  health_check_enabled: false,
  rule_integrity_check_passive: true,
  protected_paths: [],
  menus: ["Integrity Protection"],
};

const sampleAlert: FileBaselineProtectionAlert = {
  alert_id: "alert-highlight",
  agent_id: "default",
  path: "SOUL.md",
  approved_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  current_sha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  provenance: "startup_scan",
  status: "pending_review",
  detected_at: "2026-06-11T00:00:00Z",
};

function setupApiMocks(options?: {
  persona?: FileBaselineProtectionSettings;
  alerts?: FileBaselineProtectionAlert[];
}) {
  const persona = options?.persona ?? disabledPersona;
  const alerts = options?.alerts ?? [];
  mockGetFileBaselineSettings.mockResolvedValue(persona);
  mockGetPersonaAlerts.mockResolvedValue({
    enabled: persona.enabled,
    scanning: false,
    alerts,
    open_alert_count: alerts.length,
  });
  mockGetIntegritySettings.mockResolvedValue({
    ...integritySettings,
    file_baseline_enabled: persona.enabled,
    protected_paths: persona.enabled ? persona.protected_paths : [],
  });
}

function getMasterSwitch() {
  return screen.getAllByRole("switch")[0];
}

describe("IntegrityProtectionSection persona UI", () => {
  beforeEach(() => {
    setupApiMocks();
    mockUpdateFileBaselineSettings.mockImplementation(async ({ enabled }) => ({
      ...enabledPersona,
      enabled: Boolean(enabled),
    }));
    mockRestorePersonaAlert.mockResolvedValue(true);
    mockAcceptPersonaAlert.mockResolvedValue(true);
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders persona protection switch off by default (PB-S01)", async () => {
    renderWithProviders(<IntegrityProtectionSection />);
    await waitFor(() => {
      expect(screen.getByText("File Baseline Protection")).toBeInTheDocument();
    });
    const switchInput = getMasterSwitch();
    expect(switchInput).not.toBeChecked();
  });

  it("does not show drift table when persona protection is disabled", async () => {
    renderWithProviders(<IntegrityProtectionSection />);
    await waitFor(() => {
      expect(screen.getByText("File Baseline Protection")).toBeInTheDocument();
    });
    expect(screen.queryByText("Open baseline drift alerts")).not.toBeInTheDocument();
  });

  it("shows drift alerts and protected paths when enabled (PB-S20)", async () => {
    setupApiMocks({ persona: enabledPersona, alerts: [sampleAlert] });
    renderWithProviders(<IntegrityProtectionSection />);
    await waitFor(() => {
      expect(screen.getAllByText("SOUL.md").length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getByText("startup_scan")).toBeInTheDocument();
    expect(screen.getByText("Open baseline drift alerts: 1")).toBeInTheDocument();
  });

  it("reports open alert count to parent", async () => {
    const onAlertCountChange = vi.fn();
    setupApiMocks({ persona: enabledPersona, alerts: [sampleAlert] });
    renderWithProviders(
      <IntegrityProtectionSection onAlertCountChange={onAlertCountChange} />,
    );
    await waitFor(() => {
      expect(onAlertCountChange).toHaveBeenCalledWith(1);
    });
  });

  it("assigns highlight row id for deep-linked alert", async () => {
    setupApiMocks({ persona: enabledPersona, alerts: [sampleAlert] });
    renderWithProviders(
      <IntegrityProtectionSection highlightAlertId="alert-highlight" />,
    );
    await waitFor(() => {
      expect(document.getElementById("file-baseline-alert-alert-highlight")).toBeTruthy();
    });
  });

  it("enables persona protection when switch is turned on (PB-S10)", async () => {
    const user = userEvent.setup();
    renderWithProviders(<IntegrityProtectionSection />);
    await waitFor(() => {
      expect(getMasterSwitch()).toBeInTheDocument();
    });
    await user.click(getMasterSwitch());
    await waitFor(() => {
      expect(mockUpdateFileBaselineSettings).toHaveBeenCalledWith(
        expect.objectContaining({ enabled: true }),
      );
    });
  });

  it("restores alert directly without confirmation modal (PB-S42)", async () => {
    const user = userEvent.setup();
    setupApiMocks({ persona: enabledPersona, alerts: [sampleAlert] });
    renderWithProviders(<IntegrityProtectionSection />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => {
      expect(mockRestorePersonaAlert).toHaveBeenCalledWith("alert-highlight");
    });
    expect(
      screen.queryByText("Enter confirmation phrase"),
    ).not.toBeInTheDocument();
  });

  it("accepts alert directly without confirmation modal", async () => {
    const user = userEvent.setup();
    setupApiMocks({ persona: enabledPersona, alerts: [sampleAlert] });
    renderWithProviders(<IntegrityProtectionSection />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => {
      expect(mockAcceptPersonaAlert).toHaveBeenCalledWith("alert-highlight");
    });
    expect(
      screen.queryByText("Enter confirmation phrase"),
    ).not.toBeInTheDocument();
  });

  it("toggles preset file protection via per-file switch (FB-S18)", async () => {
    const user = userEvent.setup();
    mockUpdateFileBaselineSettings.mockImplementation(async (payload) => ({
      ...disabledPersona,
      ...payload,
      protected_targets: payload.protected_targets ?? disabledPersona.protected_targets,
    }));
    renderWithProviders(<IntegrityProtectionSection />);
    await waitFor(() => {
      expect(screen.getAllByText("AGENTS.md").length).toBeGreaterThanOrEqual(1);
    });
    const switches = screen.getAllByRole("switch");
    // switches[0] = master; switches[1] = SOUL.md; switches[2] = AGENTS.md
    await user.click(switches[2]);
    await waitFor(() => {
      expect(mockUpdateFileBaselineSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          protected_targets: ["SOUL.md", "AGENTS.md"],
        }),
      );
    });
  });
});

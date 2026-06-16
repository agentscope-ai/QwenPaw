import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import { IntegrityProtectionSection } from "./IntegrityProtectionSection";
import type {
  IntegrityProtectionSettings,
  FileBaselineProtectionSettings,
} from "@/api/modules/security";

const {
  mockGetFileBaselineSettings,
  mockGetIntegritySettings,
  mockUpdateFileBaselineSettings,
} = vi.hoisted(() => ({
  mockGetFileBaselineSettings: vi.fn(),
  mockGetIntegritySettings: vi.fn(),
  mockUpdateFileBaselineSettings: vi.fn(),
}));

vi.mock("@extension/file_baseline/hooks/useFileBaselineDriftWatch", () => ({
  useFileBaselineDriftWatch: vi.fn(),
}));

vi.mock("../../../../api", () => ({
  default: {
    getFileBaselineProtectionSettings: mockGetFileBaselineSettings,
    getIntegrityProtectionSettings: mockGetIntegritySettings,
    updateFileBaselineProtectionSettings: mockUpdateFileBaselineSettings,
    checkIntegrityRuleEntry: vi.fn(),
  },
}));

vi.mock("@agentscope-ai/design", async () => {
  const antd = await import("antd");
  return {
    Button: antd.Button,
    Card: antd.Card,
    Dropdown: antd.Dropdown,
    Input: antd.Input,
    Modal: antd.Modal,
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
        "security.integrityProtection.protectedFilesDesc": "Toggle per file",
        "security.integrityProtection.fileBaselineToggleTooltip": "Toggle file baseline",
        "security.integrityProtection.pathDescriptions.soul": "Persona",
        "security.integrityProtection.pathPresets.agents": "AGENTS.md",
        "security.integrityProtection.pathDescriptions.agents": "Agent rules",
        "security.integrityProtection.ruleIntegrityTitle": "Rule integrity",
        "security.integrityProtection.ruleIntegrityAction": "Check rules",
        "security.integrityProtection.emptyFindings": "No findings",
        "security.integrityProtection.fileBaselineEnableSuccess": "Persona enabled",
        "security.integrityProtection.fileBaselineDisableSuccess": "Persona disabled",
        "security.integrityProtection.loadFailed": "Load failed",
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

function setupApiMocks(options?: { persona?: FileBaselineProtectionSettings }) {
  const persona = options?.persona ?? disabledPersona;
  mockGetFileBaselineSettings.mockResolvedValue(persona);
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

  it("does not show drift alerts table when persona protection is disabled", async () => {
    renderWithProviders(<IntegrityProtectionSection />);
    await waitFor(() => {
      expect(screen.getByText("File Baseline Protection")).toBeInTheDocument();
    });
    expect(screen.queryByText("Open baseline drift alerts")).not.toBeInTheDocument();
  });

  it("shows protected paths when enabled without drift alerts table (PB-S20)", async () => {
    setupApiMocks({ persona: enabledPersona });
    renderWithProviders(<IntegrityProtectionSection />);
    await waitFor(() => {
      expect(screen.getAllByText("SOUL.md").length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.queryByText("Open baseline drift alerts")).not.toBeInTheDocument();
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

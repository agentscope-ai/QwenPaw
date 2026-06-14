import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import { HealthCheckSection } from "./HealthCheckSection";
import type { HealthCheckScanResponse } from "@/api/modules/security";

const { mockRunScan, mockRunFix } = vi.hoisted(() => ({
  mockRunScan: vi.fn(),
  mockRunFix: vi.fn(),
}));

vi.mock("@/api", () => ({
  default: {
    runIntegrityHealthCheckScan: mockRunScan,
    runIntegrityHealthCheckFix: mockRunFix,
  },
}));

vi.mock("@agentscope-ai/design", async () => {
  const antd = await import("antd");
  return {
    Button: antd.Button,
    Card: antd.Card,
    Table: antd.Table,
    Tag: antd.Tag,
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      const labels: Record<string, string> = {
        "security.healthCheck.panelTitle": "Runtime diagnostics",
        "security.healthCheck.runCheck": "Run check",
        "security.healthCheck.runCheckAgain": "Run again",
        "security.healthCheck.status.idle": "Ready",
        "security.healthCheck.status.running": "Checking",
        "security.healthCheck.status.completed": "Done",
        "security.healthCheck.carousel.idle": "Waiting",
        "security.healthCheck.carousel.runningHint": "Analyzing",
        "security.healthCheck.carousel.currentPrefix": "Checking {{item}}",
        "security.healthCheck.carousel.completed": "Check finished",
        "security.healthCheck.emptyState.intro": "Click Run check",
        "security.healthCheck.emptyState.step1": "Step 1",
        "security.healthCheck.emptyState.step2": "Step 2",
        "security.healthCheck.emptyState.step3": "Step 3",
        "security.healthCheck.summary.allClearHeadline": "All {{total}} checks passed",
        "security.healthCheck.summary.headline": "{{attention}} issues",
        "security.healthCheck.view.issuesOnly": "Issues only",
        "security.healthCheck.view.all": "All",
        "security.healthCheck.columns.group": "Category",
        "security.healthCheck.columns.check": "Check",
        "security.healthCheck.columns.status": "Status",
        "security.healthCheck.columns.detail": "Details",
        "security.healthCheck.columns.guidance": "What to do",
        "security.healthCheck.columns.action": "Action",
        "security.healthCheck.scanItems.working-dir": "Data folder",
        "security.healthCheck.scanItems.tool-guard": "Tool guard",
        "security.healthCheck.groups.environment": "Environment",
        "security.healthCheck.itemStatus.ok": "OK",
        "security.healthCheck.itemStatus.risk": "Needs attention",
        "security.healthCheck.details.working-dir.ok": "Data folder OK",
        "security.healthCheck.fix.action": "Fix",
        "security.healthCheck.actions.manual": "Manual fix needed",
        "security.healthCheck.errorHint": "Check failed",
        "security.healthCheck.retry": "Retry",
        "security.healthCheck.loadFailed": "Failed",
      };
      if (key === "security.healthCheck.carousel.currentPrefix" && options?.item) {
        return `Checking ${options.item}`;
      }
      if (key === "security.healthCheck.summary.allClearHeadline" && options?.total) {
        return `All ${options.total} checks passed`;
      }
      return labels[key] ?? String(options?.defaultValue ?? key);
    },
  }),
}));

const sampleScan: HealthCheckScanResponse = {
  scan_id: "health-scan-test",
  read_only: true,
  progress: 100,
  check_items: [
    {
      id: "working-dir",
      group: "environment",
      label: "Working directory",
      status: "ok",
      detail: "/tmp/qwenpaw",
      risk: "",
      recommendation: "",
      fix_id: null,
      deep_only: false,
    },
  ],
  risk_summary: [],
  repair_suggestions: [],
  mutated_files: [],
};

describe("HealthCheckSection", () => {
  beforeEach(() => {
    sessionStorage.clear();
    mockRunScan.mockResolvedValue(sampleScan);
    mockRunFix.mockResolvedValue({
      confirmed: true,
      selected_repair: "repair_ensure-working-dir",
      fix_id: "ensure-working-dir",
      executed: true,
      exit_code: 0,
      output: ["done"],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders single run check action", () => {
    renderWithProviders(<HealthCheckSection />);
    expect(screen.getByText("Runtime diagnostics")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run check" })).toBeInTheDocument();
  });

  it("runs scan with deep=false (HC-S01)", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HealthCheckSection />);
    await user.click(screen.getByRole("button", { name: "Run check" }));
    await waitFor(() => {
      expect(mockRunScan).toHaveBeenCalledWith(false);
    });
  });

  it("shows summary when all checks pass (HC-S03)", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HealthCheckSection />);
    await user.click(screen.getByRole("button", { name: "Run check" }));
    await waitFor(() => {
      expect(screen.getByText("All 1 checks passed")).toBeInTheDocument();
    });
  });

  it("defaults to full checklist when all checks pass (HC-S03b)", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HealthCheckSection />);
    await user.click(screen.getByRole("button", { name: "Run check" }));
    await waitFor(() => {
      expect(screen.getByText("Data folder")).toBeInTheDocument();
    });
  });

  it("defaults to issues-only view when attention items exist (HC-S03c)", async () => {
    mockRunScan.mockResolvedValueOnce({
      ...sampleScan,
      check_items: [
        {
          id: "working-dir",
          group: "environment",
          label: "Working directory",
          status: "ok",
          detail: "/tmp/qwenpaw",
          risk: "",
          recommendation: "",
          fix_id: null,
          deep_only: false,
        },
        {
          id: "tool-guard",
          group: "security",
          label: "Tool guard",
          status: "risk",
          detail: "tool_guard.enabled is false",
          risk: "disabled",
          recommendation: "enable",
          fix_id: null,
          deep_only: false,
        },
      ],
    });
    const user = userEvent.setup();
    renderWithProviders(<HealthCheckSection />);
    await user.click(screen.getByRole("button", { name: "Run check" }));
    await waitFor(() => {
      expect(screen.getByText("Manual fix needed")).toBeInTheDocument();
    });
    expect(screen.queryByText("Data folder")).not.toBeInTheDocument();
  });

  it("shows row fix action for fixable items (HC-S05)", async () => {
    mockRunScan.mockResolvedValueOnce({
      ...sampleScan,
      check_items: [
        {
          id: "working-dir",
          group: "environment",
          label: "Working directory",
          status: "risk",
          detail: "missing",
          risk: "missing dir",
          recommendation: "create dir",
          fix_id: "ensure-working-dir",
          deep_only: false,
        },
      ],
    });
    const user = userEvent.setup();
    renderWithProviders(<HealthCheckSection />);
    await user.click(screen.getByRole("button", { name: "Run check" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Fix" })).toBeInTheDocument();
    });
  });

  it("reports attention count to parent", async () => {
    mockRunScan.mockResolvedValueOnce({
      ...sampleScan,
      check_items: [
        {
          id: "working-dir",
          group: "environment",
          label: "Working directory",
          status: "risk",
          detail: "missing",
          risk: "missing dir",
          recommendation: "create dir",
          fix_id: "ensure-working-dir",
          deep_only: false,
        },
      ],
    });
    const onAttentionCountChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <HealthCheckSection onAttentionCountChange={onAttentionCountChange} />,
    );
    await user.click(screen.getByRole("button", { name: "Run check" }));
    await waitFor(() => {
      expect(onAttentionCountChange).toHaveBeenCalledWith(1);
    });
  });

  it("shows failure state when scan request rejects (HC-S07)", async () => {
    mockRunScan.mockRejectedValueOnce(new Error("network down"));
    const user = userEvent.setup();
    renderWithProviders(<HealthCheckSection />);
    await user.click(screen.getByRole("button", { name: "Run check" }));
    await waitFor(() => {
      expect(screen.getByText("Check failed")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    });
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DebugPage from "./index";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

vi.mock("./useDebugLogs", () => ({
  backendLevelColor: () => "default",
  useDebugLogs: () => ({
    backendLogs: {
      path: "qwenpaw.log",
      exists: true,
      lines: 200,
      updated_at: 1,
      size: 20,
      content: "INFO safe line",
    },
    initialLoading: false,
    backendError: "",
    autoRefresh: false,
    setAutoRefresh: vi.fn(),
    backendNewestFirst: true,
    setBackendNewestFirst: vi.fn(),
    backendLevel: "all",
    setBackendLevel: vi.fn(),
    backendQuery: "",
    setBackendQuery: vi.fn(),
    filteredBackendLines: ["INFO safe line"],
    loadBackendLogs: vi.fn(),
    handleCopyBackend: vi.fn(),
  }),
}));

describe("DebugPage", () => {
  it("explains that the administrator log response is redacted", () => {
    render(<DebugPage />);

    expect(screen.getByText("Sensitive data redacted")).toBeTruthy();
    expect(screen.getByText("Log source")).toBeTruthy();
    expect(screen.getByText("qwenpaw.log")).toBeTruthy();
  });
});

// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PYPI_URL } from "./constants";

const mocks = vi.hoisted(() => ({
  getVersion: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../api", () => ({
  default: { getVersion: mocks.getVersion },
}));

vi.mock("../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

vi.mock("../contexts/DesktopUpdateContext", () => ({
  useDesktopUpdate: () => ({
    phase: "idle",
    isBackground: false,
    hasUpdate: false,
    supportsLaterInstall: false,
    version: "",
    body: "",
    downloaded: 0,
    total: null,
    error: null,
    installDownloaded: vi.fn(),
    startBackgroundDownload: vi.fn(),
    startInstall: vi.fn(),
  }),
}));

vi.mock("../plugins/registry/Slot", () => ({
  Slot: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("../tauri/backendRuntime", () => ({
  isDesktopApp: () => false,
}));

import AppBrand from "./AppBrand";

describe("AppBrand", () => {
  beforeEach(() => {
    mocks.getVersion.mockResolvedValue({ version: "1.0.0" });
    const oldRelease = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce({
          json: () =>
            Promise.resolve({
              info: { version: "2.0.0" },
              releases: {
                "2.0.0": [{ upload_time_iso_8601: oldRelease }],
              },
            }),
        })
        .mockResolvedValue({ ok: false }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the shared logo, version, action, and update reminder together", async () => {
    const view = render(
      <AppBrand action={<button type="button">Collapse</button>} />,
    );

    expect(screen.getByRole("img", { name: "QwenPaw" })).toHaveAttribute(
      "src",
      "/logo-light.svg",
    );
    expect(screen.getByRole("button", { name: "Collapse" })).toBeVisible();
    const version = await screen.findByText("v1.0.0");
    await waitFor(() => {
      expect(document.querySelector(".ant-badge-dot")).toBeInTheDocument();
    });

    fireEvent.click(version);

    expect(await screen.findByText("Version 2.0.0")).toBeVisible();

    view.unmount();
    render(<AppBrand />);
    expect(await screen.findByText("v1.0.0")).toBeVisible();
    expect(mocks.getVersion).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith(PYPI_URL);
  });
});

// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
    mocks.getVersion.mockReset().mockResolvedValue({ version: "1.0.0" });
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
    render(<AppBrand action={<button type="button">Collapse</button>} />);

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
  });

  it("uses a provided sidebar version without requesting it again", async () => {
    render(<AppBrand version="1.2.3" />);

    expect(await screen.findByText("v1.2.3")).toBeVisible();
    expect(mocks.getVersion).not.toHaveBeenCalled();
  });

  it("stays mounted while its sidebar presentation is hidden", async () => {
    const { container, rerender } = render(<AppBrand version="1.2.3" />);

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    rerender(<AppBrand hidden version="1.2.3" />);

    expect(
      container.querySelector('img[alt="QwenPaw"]')?.closest("div"),
    ).toHaveAttribute("hidden");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

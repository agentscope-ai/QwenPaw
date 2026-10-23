import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import StartupProgressBanner from "./index";

const healthz = (status: number, phase?: string) =>
  new Response(JSON.stringify(phase === undefined ? {} : { phase }), {
    status,
    headers: { "Content-Type": "application/json" },
  });

describe("StartupProgressBanner", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows the phase while starting and hides once complete", async () => {
    fetchMock
      .mockResolvedValueOnce(healthz(503, "agents"))
      .mockResolvedValueOnce(healthz(200, "finalizing"))
      .mockResolvedValueOnce(healthz(200, "complete"));

    render(<StartupProgressBanner />);
    await act(async () => {});
    expect(screen.getByText("startupProgress.agents")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByText("startupProgress.finalizing")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.queryByText(/startupProgress\./)).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("renders nothing for backends that do not report a phase", async () => {
    fetchMock.mockResolvedValueOnce(healthz(200));

    const { container } = render(<StartupProgressBanner />);
    await act(async () => {});

    expect(container.textContent).toBe("");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("stops polling when the probe fails", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("network"));

    const { container } = render(<StartupProgressBanner />);
    await act(async () => {});

    expect(container.textContent).toBe("");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

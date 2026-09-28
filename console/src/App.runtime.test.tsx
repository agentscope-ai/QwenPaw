import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { hubHealth } from "./test/hubFixtures";

const hubApiMock = vi.hoisted(() => ({
  getHealth: vi.fn(),
  restartOwnRuntime: vi.fn(),
}));

vi.mock("./api/modules/hub", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/modules/hub")>();
  return { ...actual, hubApi: hubApiMock };
});

vi.mock("./tauri/BackendLoadingPage", () => ({
  default: ({
    status,
    errorMessage,
  }: {
    status: string;
    errorMessage?: string;
  }) => (
    <div data-testid="runtime-loading" data-status={status}>
      {errorMessage}
    </div>
  ),
}));

import { getAppThemeToken, RuntimeAvailabilityGuard } from "./App";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("RuntimeAvailabilityGuard", () => {
  it("polls a slow runtime before mounting the application", async () => {
    vi.useFakeTimers();
    hubApiMock.getHealth
      .mockResolvedValueOnce(hubHealth({ runtime_state: "starting" }))
      .mockResolvedValueOnce(hubHealth({ runtime_state: "running" }));

    render(
      <RuntimeAvailabilityGuard enabled>
        <div>runtime application</div>
      </RuntimeAvailabilityGuard>,
    );
    await act(async () => {});

    expect(screen.getByTestId("runtime-loading")).toBeInTheDocument();
    expect(screen.queryByText("runtime application")).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByText("runtime application")).toBeInTheDocument();
    expect(hubApiMock.getHealth).toHaveBeenCalledTimes(2);
  });

  it("shows the lifecycle failure instead of mounting the application", async () => {
    hubApiMock.getHealth.mockResolvedValue(
      hubHealth({
        status: "degraded",
        runtime_state: "failed",
        runtime_last_error: "runtime readiness timed out",
      }),
    );

    render(
      <RuntimeAvailabilityGuard enabled>
        <div>runtime application</div>
      </RuntimeAvailabilityGuard>,
    );
    await act(async () => {});

    expect(screen.getByTestId("runtime-loading")).toHaveAttribute(
      "data-status",
      "error",
    );
    expect(screen.getByText("runtime readiness timed out")).toBeInTheDocument();
    expect(screen.queryByText("runtime application")).not.toBeInTheDocument();
  });
});

describe("getAppThemeToken", () => {
  it("uses the shared control radius when unset", () => {
    const token = getAppThemeToken({}, false);

    expect(token.colorPrimary).toBe("#FF7F16");
    expect(token.borderRadius).toBe(10);
  });

  it("passes a configured radius through to antd", () => {
    expect(getAppThemeToken({ radius: "12px" }, false).borderRadius).toBe(12);
  });

  it("grows control heights with larger fonts without shrinking defaults", () => {
    const small = getAppThemeToken({}, false, 12);
    const large = getAppThemeToken({}, false, 20);

    expect(small.controlHeight).toBe(32);
    expect(small.controlHeightSM).toBe(24);
    expect(large.controlHeight).toBe(46);
    expect(large.controlHeightSM).toBe(34);
    expect(large.controlHeightLG).toBe(57);
  });
});

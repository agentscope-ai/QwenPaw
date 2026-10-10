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

import {
  getAppComponentTokens,
  getAppThemeToken,
  RuntimeAvailabilityGuard,
} from "./App";
import { getUiFontScale } from "./utils/uiFontSizePreference";

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

describe("getAppComponentTokens", () => {
  // Mirrors the fixed modal typography Spark ships in its antd theme.
  const spark = {
    Modal: { headerBg: "#fff", titleFontSize: 16 },
    Alert: { fontSize: 12 },
  };

  it("keeps Spark's component tokens at the default font size", () => {
    const tokens = getAppComponentTokens(spark);

    expect(tokens.Modal).toEqual(spark.Modal);
    expect(tokens.Alert).toBe(spark.Alert);
  });

  it("scales the pinned modal title with the console font size", () => {
    expect(getAppComponentTokens(spark, 20).Modal).toEqual({
      headerBg: "#fff",
      titleFontSize: 16 * getUiFontScale(20),
    });
    expect(getAppComponentTokens(spark, 12).Modal?.titleFontSize).toBe(
      16 * getUiFontScale(12),
    );
  });

  it("leaves themes without a pinned modal title untouched", () => {
    const base = { Alert: { fontSize: 12 } };

    expect(getAppComponentTokens(base, 20)).toBe(base);
  });
});

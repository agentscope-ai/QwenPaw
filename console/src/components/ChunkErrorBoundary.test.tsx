import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../i18n", () => ({
  default: { t: (key: string) => key },
}));

vi.mock("../api/modules/hub", () => ({
  hubApi: { restartOwnRuntime: vi.fn() },
}));

import { hubApi } from "../api/modules/hub";
import { ChunkErrorBoundary } from "./ChunkErrorBoundary";

function BrokenPage(): ReactElement {
  throw new Error("render failed");
}

describe("ChunkErrorBoundary runtime recovery", () => {
  afterEach(() => vi.restoreAllMocks());

  it("offers Hub users a runtime restart when a page fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.mocked(hubApi.restartOwnRuntime).mockRejectedValueOnce(
      new Error("restart failed"),
    );

    render(
      <ChunkErrorBoundary canRestartRuntime>
        <BrokenPage />
      </ChunkErrorBoundary>,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "account.runtimeRestart" }),
    );

    await waitFor(() => {
      expect(hubApi.restartOwnRuntime).toHaveBeenCalledOnce();
      expect(screen.getByText("restart failed")).toBeInTheDocument();
    });
  });

  it("does not expose Hub recovery in standalone mode", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <ChunkErrorBoundary>
        <BrokenPage />
      </ChunkErrorBoundary>,
    );

    expect(
      screen.queryByRole("button", { name: "account.runtimeRestart" }),
    ).not.toBeInTheDocument();
  });
});
/**
 * A component that throws a DOM-mutation error while  is true,
 * then renders successfully once the flag is cleared - the transient race
 * this boundary must recover from.
 */
function FlakyPage(props: { shouldFail: { current: boolean } }): ReactElement {
  if (props.shouldFail.current) {
    const error = new Error(
      "Failed to execute 'insertBefore' on 'Node': The node before which " +
        "the new node is to be inserted is not a child of this node.",
    );
    error.name = "NotFoundError";
    throw error;
  }
  return <div>recovered</div>;
}

describe("ChunkErrorBoundary retry for transient DOM errors", () => {
  afterEach(() => vi.restoreAllMocks());

  it("re-renders in place and recovers from a DOM mutation error", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const shouldFail = { current: true };

    render(
      <ChunkErrorBoundary>
        <FlakyPage shouldFail={shouldFail} />
      </ChunkErrorBoundary>,
    );

    expect(screen.getByText("chunkError.genericTitle")).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "chunkError.retry" });

    // The underlying race has passed by the time the user retries.
    shouldFail.current = false;
    fireEvent.click(retry);

    await waitFor(() => {
      expect(screen.getByText("recovered")).toBeInTheDocument();
    });
  });

  it("drops the retry button once retries are exhausted", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const shouldFail = { current: true };

    render(
      <ChunkErrorBoundary>
        <FlakyPage shouldFail={shouldFail} />
      </ChunkErrorBoundary>,
    );

    for (let i = 0; i < 2; i += 1) {
      const retry = screen.queryByRole("button", { name: "chunkError.retry" });
      expect(retry).not.toBeNull();
      fireEvent.click(retry as HTMLElement);
    }

    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "chunkError.retry" }),
      ).toBeNull();
    });
    expect(
      screen.getByRole("button", { name: "chunkError.reload" }),
    ).toBeInTheDocument();
  });

  it("offers no in-place retry for a chunk load error", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    function BrokenChunk(): ReactElement {
      throw new Error("Loading chunk 42 failed.");
    }

    render(
      <ChunkErrorBoundary>
        <BrokenChunk />
      </ChunkErrorBoundary>,
    );

    expect(screen.getByText("chunkError.title")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "chunkError.retry" }),
    ).toBeNull();
  });
});

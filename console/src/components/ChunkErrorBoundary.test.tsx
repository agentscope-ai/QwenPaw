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

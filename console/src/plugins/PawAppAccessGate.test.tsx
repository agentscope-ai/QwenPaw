import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PawAppAccessGate } from "./PawAppAccessGate";
import { prepareBrowserSession } from "./pawapp-sdk/browserSession";
import { loadPawApp } from "./usePluginLoader";

vi.mock("./pawapp-sdk/browserSession", () => ({
  prepareBrowserSession: vi.fn(),
}));
vi.mock("./usePluginLoader", () => ({
  loadPawApp: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("../api/config", () => ({ getApiToken: () => "account-token" }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (_key: string, fallback: string) => fallback }),
}));
beforeEach(() => vi.clearAllMocks());

describe("PawAppAccessGate", () => {
  it("waits for authentication even when the entry is already cached", async () => {
    let ready!: (seconds: number) => void;
    vi.mocked(prepareBrowserSession).mockReturnValue(
      new Promise((resolve) => {
        ready = resolve;
      }),
    );
    render(
      <PawAppAccessGate appId="qwenpaw-creator" loadEntry>
        <iframe title="Creator" />
      </PawAppAccessGate>,
    );
    expect(screen.queryByTitle("Creator")).toBeNull();
    expect(loadPawApp).not.toHaveBeenCalled();
    await act(async () => ready(900));
    expect(await screen.findByTitle("Creator")).toBeInTheDocument();
    expect(loadPawApp).toHaveBeenCalledWith("qwenpaw-creator");
  });
  it("shows auth failure without navigating an iframe", async () => {
    vi.mocked(prepareBrowserSession).mockRejectedValue(
      new Error("Not authenticated"),
    );
    render(
      <PawAppAccessGate appId="qwenpaw-creator">
        <iframe title="Creator" />
      </PawAppAccessGate>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Not authenticated",
    );
    expect(screen.queryByTitle("Creator")).toBeNull();
  });
  it("renews without remounting the app", async () => {
    vi.mocked(prepareBrowserSession).mockResolvedValue(61);
    const view = render(
      <PawAppAccessGate appId="qwenpaw-creator">
        <iframe title="Creator" />
      </PawAppAccessGate>,
    );
    const frame = await screen.findByTitle("Creator");
    await waitFor(
      () => expect(prepareBrowserSession).toHaveBeenCalledTimes(2),
      { timeout: 2000 },
    );
    expect(screen.getByTitle("Creator")).toBe(frame);
    view.unmount();
  });
});

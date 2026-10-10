// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PawAppAccessGate } from "./PawAppAccessGate";

const mocks = vi.hoisted(() => ({ prepare: vi.fn(), token: "user-a" }));
vi.mock("./pawapp-sdk/browserSession", () => ({
  prepareBrowserSession: mocks.prepare,
}));
vi.mock("../api/config", () => ({ getApiToken: () => mocks.token }));
vi.mock("./usePluginLoader", () => ({ loadPawApp: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (s: string) => s }),
}));
vi.mock("antd", () => ({
  Spin: () => <span>preparing</span>,
  Alert: ({ message }: { message: string }) => <span>{message}</span>,
  Button: ({ children }: { children: React.ReactNode }) => (
    <button>{children}</button>
  ),
}));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  mocks.prepare.mockReset();
  mocks.token = "user-a";
});

describe("PawApp mount authentication", () => {
  it("waits before mounting iframe content and renews while mounted", async () => {
    vi.useFakeTimers();
    let resolve!: (seconds: number) => void;
    mocks.prepare.mockReturnValueOnce(
      new Promise<number>((done) => {
        resolve = done;
      }),
    );
    mocks.prepare.mockResolvedValue(900);
    render(
      <PawAppAccessGate appId="my_app">
        <span>app content</span>
      </PawAppAccessGate>,
    );
    expect(screen.queryByText("app content")).toBeNull();
    await act(async () => {
      resolve(900);
    });
    expect(screen.getByText("app content")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(840000);
    });
    expect(mocks.prepare).toHaveBeenCalledTimes(2);
  });

  it("unmounts old content on account change until reauthorized", async () => {
    mocks.prepare.mockResolvedValueOnce(null);
    await act(async () => {
      render(
        <PawAppAccessGate appId="my_app">
          <span>app content</span>
        </PawAppAccessGate>,
      );
    });
    expect(screen.getByText("app content")).toBeTruthy();
    mocks.prepare.mockReturnValue(new Promise(() => {}));
    await act(async () => {
      mocks.token = "user-b";
      window.dispatchEvent(new Event("qwenpaw:auth-changed"));
    });
    expect(screen.queryByText("app content")).toBeNull();
  });
});

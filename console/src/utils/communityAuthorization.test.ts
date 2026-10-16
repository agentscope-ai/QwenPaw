import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { invoke, isTauri } from "@/test/tauri-mock";
import {
  openAuthorizationUrl,
  reserveAuthorizationWindow,
} from "./communityAuthorization";
import { openExternalLinkChecked } from "./openExternalLink";
const url = "https://platform.agentscope.io/cli/login?source=qwenpaw-community";
beforeEach(() => {
  invoke.mockReset();
  invoke.mockResolvedValue(undefined);
  isTauri.mockReturnValue(false);
  delete window.pywebview;
  vi.spyOn(window, "open").mockReturnValue(null);
});
afterEach(() => {
  vi.restoreAllMocks();
  delete window.pywebview;
  isTauri.mockReturnValue(false);
});
it("opens Tauri authorization in the system browser without a WebView popup", async () => {
  isTauri.mockReturnValue(true);
  const popup = reserveAuthorizationWindow("Waiting");
  expect(popup).toBeNull();
  await openAuthorizationUrl(url, popup);
  expect(invoke).toHaveBeenCalledWith("open_external_link", { url });
  expect(window.open).not.toHaveBeenCalled();
});
it("opens legacy desktop authorization through pywebview", async () => {
  const open = vi.fn().mockResolvedValue(undefined);
  window.pywebview = {
    api: { open_external_link: open },
  } as typeof window.pywebview;
  await openAuthorizationUrl(url, reserveAuthorizationWindow("Waiting"));
  expect(open).toHaveBeenCalledWith(url);
  expect(window.open).not.toHaveBeenCalled();
  expect(invoke).not.toHaveBeenCalled();
});
it("reserves a referrer-free browser window before awaiting authorization", async () => {
  const popup = {
    document: document.implementation.createHTMLDocument(),
    opener: {},
    location: { replace: vi.fn() },
  };
  vi.mocked(window.open).mockReturnValue(popup as unknown as Window);
  const reserved = reserveAuthorizationWindow("Waiting");
  expect(popup.opener).toBeNull();
  expect(
    popup.document
      .querySelector('meta[name="referrer"]')
      ?.getAttribute("content"),
  ).toBe("no-referrer");
  await openAuthorizationUrl(url, reserved);
  expect(popup.location.replace).toHaveBeenCalledWith(url);
});
it("reports blocked browser popups before starting a flow", () => {
  expect(() => reserveAuthorizationWindow("Waiting")).toThrow("popup_blocked");
});
it.each([
  "https://evil.test/cli/login",
  "javascript:alert(1)",
  "https://user:password@platform.agentscope.io/cli/login",
])("rejects untrusted authorization URL %s", async (url) => {
  await expect(openAuthorizationUrl(url, null)).rejects.toThrow(
    "invalid_authorization_url",
  );
  expect(invoke).not.toHaveBeenCalled();
  expect(window.open).not.toHaveBeenCalled();
});
it("reports native opener failures without replacing the app page", async () => {
  isTauri.mockReturnValue(true);
  invoke.mockRejectedValue(new Error("native failed"));
  await expect(openAuthorizationUrl(url, null)).rejects.toThrow(
    "external_open_failed",
  );
  expect(window.open).not.toHaveBeenCalled();
});
it.each(["write", "ask"])(
  "opens the Platform %s editor with Tauri",
  async (path) => {
    isTauri.mockReturnValue(true);
    const url = `https://platform.agentscope.io/community/${path}`;
    await openExternalLinkChecked(url);
    expect(invoke).toHaveBeenCalledWith("open_external_link", { url });
    expect(window.open).not.toHaveBeenCalled();
  },
);

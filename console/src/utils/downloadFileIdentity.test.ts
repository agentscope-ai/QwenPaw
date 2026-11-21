import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { downloadFileFromUrl } from "./downloadFileFromUrl";
import { adoptAccessSession, clearAccessSession } from "../api/authSession";
import { setApiAuthMode } from "../api/config";
import { invoke, isTauri, save } from "../test/tauri-mock";
const url = "/api/console/artifacts/owned/download";
beforeEach(() => {
  clearAccessSession(false);
  setApiAuthMode("multi_user");
  adoptAccessSession({ token: "owner-fixture", username: "owner" }, false);
  vi.mocked(isTauri).mockReturnValue(false);
  vi.stubGlobal("URL", URL);
  URL.createObjectURL = vi.fn(() => "blob:fixture");
});
afterEach(() => {
  clearAccessSession(false);
  setApiAuthMode("legacy");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("does not save a previous account's PDF when identity changes during download", async () => {
  let finish!: (blob: Blob) => void;
  const response = new Response("%PDF-fixture");
  const readBlob = vi.spyOn(response, "blob").mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
  const pending = downloadFileFromUrl(url, "简报.pdf", {
    headers: { "X-Agent-Id": "agent-a" },
  });
  await vi.waitFor(() => expect(readBlob).toHaveBeenCalled());
  clearAccessSession(false);
  finish(new Blob(["%PDF-private"]));
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it("does not use captured credentials after switching accounts in a native save dialog", async () => {
  vi.mocked(isTauri).mockReturnValue(true);
  let finish!: (path: string) => void;
  vi.mocked(save).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const pending = downloadFileFromUrl(url, "简报.pdf", {
    headers: { Authorization: "Bearer owner-fixture" },
  });
  await vi.waitFor(() => expect(save).toHaveBeenCalled());
  clearAccessSession(false);
  finish("C:/fixture/简报.pdf");
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  expect(invoke).not.toHaveBeenCalled();
});

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { readFileResponse } from "./fileAccess";
import { adoptAccessSession, clearAccessSession } from "./authSession";
import { setApiAuthMode } from "./config";

beforeEach(() => {
  clearAccessSession(false);
  setApiAuthMode("multi_user");
  adoptAccessSession({ token: "expired-fixture", username: "owner" }, false);
});
afterEach(() => {
  clearAccessSession(false);
  setApiAuthMode("legacy");
  vi.unstubAllGlobals();
});

it("renews an expired file-card token and keeps the requested agent on the retried PDF", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options: RequestInit) => {
      calls.push(url);
      if (url.endsWith("/auth/refresh"))
        return Response.json({ token: "fresh-fixture", username: "owner" });
      expect(url).not.toContain("token=");
      const headers = new Headers(options.headers);
      expect(headers.get("X-Agent-Id")).toBe("report-agent");
      return headers.get("Authorization") === "Bearer fresh-fixture"
        ? new Response("%PDF-owned", {
            headers: { "Content-Type": "application/pdf" },
          })
        : new Response("{}", { status: 401 });
    }),
  );
  await expect(
    readFileResponse(
      "/api/console/artifacts/owned/download?token=historical",
      { agentId: "report-agent" },
      (response) => response.text(),
    ),
  ).resolves.toBe("%PDF-owned");
  expect(calls.filter((url) => url.endsWith("/auth/refresh"))).toHaveLength(1);
});

it("never renders a former account's file if identity changes while the response is in flight", async () => {
  let finish!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    ),
  );
  const pending = readFileResponse(
    "/api/console/artifacts/owned/download",
    { agentId: "report-agent" },
    (response) => response.text(),
  );
  clearAccessSession(false);
  finish(new Response("former-account-private-data"));
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
});

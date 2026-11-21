// @vitest-environment jsdom
// @vitest-environment-options {"url":"http://192.168.1.10:18089/chat/demo"}
import { afterEach, expect, it, vi } from "vitest";
import { downloadFileFromUrl } from "../../utils/downloadFileFromUrl";
import { artifactIdFromDownloadUrl } from "./artifactDownloadLink";
import { isTauri } from "../../test/tauri-mock";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("downloads from the visited LAN server with authentication, not the client's localhost", async () => {
  isTauri.mockReturnValue(false);
  const fetcher = vi.fn().mockResolvedValue(
    new Response("%PDF-report", {
      headers: {
        "Content-Disposition":
          "attachment; filename*=UTF-8''%E6%8A%A5%E5%91%8A.pdf",
      },
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  URL.createObjectURL = vi.fn(() => "blob:report");
  URL.revokeObjectURL = vi.fn();
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  const path =
    "/api/console/artifacts/bd20d801-5fa2-4dd0-8d5e-691806601b5b/download";
  expect(artifactIdFromDownloadUrl(path)).toBe(
    "bd20d801-5fa2-4dd0-8d5e-691806601b5b",
  );
  expect(artifactIdFromDownloadUrl("http://127.0.0.1:18089" + path)).toBeNull();
  await downloadFileFromUrl(path, "fallback", {
    headers: { Authorization: "Bearer test-only", "X-Agent-Id": "default" },
    preferResponseFilename: true,
  });
  const [requestedUrl, options] = fetcher.mock.calls[0];
  expect(new URL(requestedUrl, window.location.href).href).toBe(
    "http://192.168.1.10:18089" + path,
  );
  const headers = new Headers(options.headers);
  expect(headers.get("Authorization")).toBe("Bearer test-only");
  expect(headers.get("X-Agent-Id")).toBe("default");
  expect(click).toHaveBeenCalled();
  expect(
    document.querySelector<HTMLAnchorElement>("a[download]")?.download,
  ).toBe("报告.pdf");
  await new Promise((resolve) => setTimeout(resolve, 0));
});

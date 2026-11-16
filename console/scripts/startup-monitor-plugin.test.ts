import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { runInNewContext } from "node:vm";
import { afterEach, describe, expect, it, vi } from "vitest";

const runNode = promisify(execFile);
const buildMonitor = `
  import { loadConfigFromFile } from "vite";
  const loaded = await loadConfigFromFile(
    { command: "build", mode: "production" }, "vite.config.ts",
  );
  const plugin = loaded.config.plugins.find(p => p.name === "console-startup-monitor");
  const tags = await plugin.transformIndexHtml.handler("", { filename: "index.html", path: "/" });
  process.stdout.write(tags[0].children);
`;

const originalUrl = location.href;
let entry: HTMLScriptElement;

afterEach(async () => {
  document.body.innerHTML = '<div id="root">Mounted</div>';
  await Promise.resolve();
  entry?.remove();
  document.body.innerHTML = "";
  sessionStorage.clear();
  delete window.__qpBase;
  vi.useRealTimers();
  history.replaceState(null, "", originalUrl);
});

describe("standalone startup monitor bundle", () => {
  it.each([
    ["", "", "/api/version"],
    ["/app/qwenpaw/web", "", "/app/qwenpaw/web/api/version"],
    ["/app/qwenpaw/web", "/backend", "/backend/api/version"],
  ])(
    "checks readiness with runtime %s and API base %s",
    async (base, apiBase, versionPath) => {
      const { stdout: monitor } = await runNode(
        process.execPath,
        ["--input-type=module", "-e", buildMonitor],
        {
          cwd: process.cwd(),
          env: { ...process.env, VITE_API_BASE_URL: apiBase },
        },
      );
      vi.useFakeTimers();
      history.replaceState(null, "", `${base}/chat`);
      window.__qpBase = base;
      document.body.innerHTML =
        '<div id="root"><div class="qwenpaw-boot"><div class="qwenpaw-boot__content">Loading</div></div></div>';
      entry = document.createElement("script");
      entry.type = "module";
      entry.src = `${location.origin}${base}/assets/old-entry.js`;
      document.head.append(entry);
      sessionStorage.setItem(
        "qwenpaw:chunk-reload-build",
        JSON.stringify({ build: entry.src, attempts: 2 }),
      );
      const fetch = vi.fn(async (input: string) => {
        const path = new URL(input).pathname;
        if (path === versionPath) return Response.json({ version: "2.2.2" });
        if (path === `${base}/chat`)
          return new Response(
            `<base href="${base}/"><script type="module" src="./assets/new-entry.js"></script>`,
            { headers: { "content-type": "text/html" } },
          );
        if (path === `${base}/assets/new-entry.js`)
          return new Response("export default 42;", {
            headers: { "content-type": "text/javascript" },
          });
        return new Response(null, { status: 404 });
      });
      runInNewContext(monitor, {
        window,
        document,
        navigator,
        localStorage,
        MutationObserver,
        HTMLScriptElement,
        HTMLLinkElement,
        ErrorEvent,
        URL,
        DOMParser,
        AbortController,
        DOMException,
        performance,
        Date,
        setTimeout,
        clearTimeout,
        fetch,
      });
      entry.dispatchEvent(new Event("error"));
      await vi.advanceTimersByTimeAsync(2000);
      expect(fetch.mock.calls.map(([url]) => new URL(url).pathname)).toContain(
        versionPath,
      );
      expect(
        JSON.parse(sessionStorage.getItem("qwenpaw:chunk-diagnostic")!),
      ).toMatchObject({
        serverReadiness: { outcome: "ready", attempts: 3 },
        automaticReload: { reason: "limit-reached" },
      });
    },
  );
});

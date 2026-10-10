import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installStartupMonitor } from "./monitor";
import {
  captureChunkDiagnostic,
  readChunkDiagnostic,
  saveChunkDiagnostic,
} from "../utils/chunkDiagnostics";
import { reloadAfterChunkError } from "../utils/chunkRecovery";
import { copyText } from "../utils/clipboard";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import ru from "../locales/ru.json";
import pt from "../locales/pt-BR.json";
import id from "../locales/id.json";
import viLocale from "../locales/vi.json";

vi.mock("../utils/chunkRecovery", async (original) => ({
  ...(await original<typeof import("../utils/chunkRecovery")>()),
  reloadAfterChunkError: vi.fn(),
}));
vi.mock("../utils/clipboard", () => ({
  copyText: vi.fn().mockResolvedValue(undefined),
}));

const translations = {
  en: en.chunkError,
  zh: zh.chunkError,
  ja: ja.chunkError,
  ru: ru.chunkError,
  "pt-BR": pt.chunkError,
  id: id.chunkError,
  vi: viLocale.chunkError,
};
let stop: () => void;
let entry: HTMLScriptElement;

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  vi.mocked(reloadAfterChunkError).mockImplementation((persist) => {
    persist?.({ reason: "reload", attempts: 1, maxAttempts: 2 });
    return true;
  });
  localStorage.clear();
  sessionStorage.clear();
  vi.spyOn(navigator, "language", "get").mockReturnValue("en");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(null, {
        status: 200,
        headers: { "content-type": "text/javascript" },
      }),
    ),
  );
  document.body.innerHTML =
    '<div id="root"><div class="qwenpaw-boot"><div class="qwenpaw-boot__content">Loading Console</div></div></div>';
  entry = document.createElement("script");
  entry.type = "module";
  entry.src = `${location.origin}/assets/entry.js`;
  document.head.append(entry);
  stop = installStartupMonitor(translations);
});

afterEach(() => {
  stop();
  document.querySelectorAll("script, link").forEach((node) => node.remove());
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("Console startup recovery", () => {
  it("captures an entry failure before any React module runs", async () => {
    entry.dispatchEvent(new Event("error"));
    expect(readChunkDiagnostic()).toMatchObject({
      phase: "startup",
      startupFailure: "resource",
      frontendBuild: entry.src,
      resourceUrl: entry.src,
      automaticReloadAttempted: false,
      recheck: null,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(readChunkDiagnostic()).toMatchObject({
      automaticReloadAttempted: true,
      automaticReload: { reason: "reload", attempts: 1, maxAttempts: 2 },
      recheck: { status: 200, outcome: "available" },
    });
    expect(reloadAfterChunkError).toHaveBeenCalledOnce();
    expect(document.querySelector("details")!.open).toBe(false);
    expect(
      [...document.querySelectorAll("button")].map((node) => node.textContent),
    ).toEqual([en.chunkError.copy, en.chunkError.reload]);
  });

  it("keeps the observed failed dependency distinct from the entry build", async () => {
    const dependency = document.createElement("link");
    dependency.rel = "modulepreload";
    dependency.href = `${location.origin}/assets/vendor.js`;
    document.head.append(dependency);
    dependency.dispatchEvent(new Event("error"));
    expect(readChunkDiagnostic()).toBeNull();
    entry.dispatchEvent(new Event("error"));
    await vi.advanceTimersByTimeAsync(0);
    expect(readChunkDiagnostic()).toMatchObject({
      resourceUrl: dependency.href,
      frontendBuild: entry.src,
    });
  });

  it("does not refresh for a failed preload when the application still mounts", async () => {
    const dependency = document.createElement("link");
    dependency.rel = "modulepreload";
    document.head.append(dependency);
    dependency.dispatchEvent(new Event("error"));
    document
      .getElementById("root")!
      .replaceChildren(document.createElement("main"));
    await vi.advanceTimersByTimeAsync(30_000);
    expect(readChunkDiagnostic()).toBeNull();
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
  });

  it("preserves a runtime error without automatically refreshing", () => {
    window.dispatchEvent(
      new ErrorEvent("error", {
        error: new TypeError("Initialization failed"),
        message: "Initialization failed",
        filename: entry.src,
      }),
    );
    expect(readChunkDiagnostic()).toMatchObject({
      startupFailure: "runtime",
      originalError: { name: "TypeError", message: "Initialization failed" },
      automaticReloadAttempted: false,
    });
    expect(document.body.textContent).toContain(en.chunkError.startup.runtime);
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
  });

  it.each([
    [new TypeError("Failed to fetch"), "runtime"],
    [
      new TypeError(
        "Failed to fetch dynamically imported module: /assets/locale.js",
      ),
      "resource",
    ],
  ])("distinguishes rejected API and module promises", async (reason, kind) => {
    window.dispatchEvent(
      new PromiseRejectionEvent("unhandledrejection", {
        promise: Promise.resolve(),
        reason,
      }),
    );
    await vi.advanceTimersByTimeAsync(0);
    expect(readChunkDiagnostic()?.startupFailure).toBe(kind);
    expect(reloadAfterChunkError).toHaveBeenCalledTimes(
      kind === "resource" ? 1 : 0,
    );
  });

  it("shows manual recovery after a startup timeout without inventing a resource failure", async () => {
    await vi.advanceTimersByTimeAsync(29_999);
    expect(readChunkDiagnostic()).toBeNull();
    await vi.advanceTimersByTimeAsync(1);
    expect(readChunkDiagnostic()).toMatchObject({
      startupFailure: "timeout",
      elapsedMs: 30_000,
      resourceUrl: null,
      originalResourceStatus: null,
      automaticReloadAttempted: false,
    });
    expect(document.body.textContent).toContain(en.chunkError.startup.timeout);
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
  });

  it.each(["runtime", "timeout"] as const)(
    "allows a successful mount after a %s failure without refreshing",
    async (kind) => {
      const removeListener = vi.spyOn(window, "removeEventListener");
      if (kind === "runtime") {
        window.dispatchEvent(
          new ErrorEvent("error", { error: new Error("Startup failed") }),
        );
      } else {
        await vi.advanceTimersByTimeAsync(30_000);
      }
      expect(document.body.textContent).toContain(en.chunkError.startup[kind]);
      expect(document.querySelector(".qwenpaw-boot--error")).not.toBeNull();
      const diagnostic = readChunkDiagnostic();
      expect(diagnostic?.startupFailure).toBe(kind);

      document.getElementById("root")!.innerHTML = "<main>Loaded</main>";
      await vi.advanceTimersByTimeAsync(0);
      expect(removeListener).toHaveBeenCalledWith(
        "error",
        expect.any(Function),
        true,
      );
      expect(removeListener).toHaveBeenCalledWith(
        "unhandledrejection",
        expect.any(Function),
      );
      entry.dispatchEvent(new Event("error"));
      await vi.advanceTimersByTimeAsync(30_000);
      expect(document.querySelector(".qwenpaw-boot")).toBeNull();
      expect(document.body.textContent).toBe("Loaded");
      expect(readChunkDiagnostic()).toEqual(diagnostic);
      expect(reloadAfterChunkError).not.toHaveBeenCalled();
    },
  );

  it("stops collecting failures when React replaces the loading placeholder", async () => {
    document.getElementById("root")!.innerHTML = "<main>Loaded</main>";
    await vi.advanceTimersByTimeAsync(0);
    entry.dispatchEvent(new Event("error"));
    await vi.advanceTimersByTimeAsync(30_000);
    expect(readChunkDiagnostic()).toBeNull();
    expect(document.body.textContent).toBe("Loaded");
  });

  it("cancels pending recovery if rendering succeeds while the resource is being rechecked", async () => {
    let resolve: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((complete) => {
          resolve = complete;
        }),
      ),
    );
    entry.dispatchEvent(new Event("error"));
    document.getElementById("root")!.innerHTML = "<main>Loaded</main>";
    await vi.advanceTimersByTimeAsync(0);
    resolve!(new Response(null, { status: 200 }));
    await vi.advanceTimersByTimeAsync(0);
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
    expect(document.body.textContent).toBe("Loaded");
  });

  it("includes the diagnostic saved before the previous automatic refresh", () => {
    const previous = captureChunkDiagnostic(
      new Error("Failed to load old entry"),
    );
    previous.automaticReloadAttempted = true;
    saveChunkDiagnostic(previous);
    window.dispatchEvent(
      new ErrorEvent("error", { error: new Error("Startup failed") }),
    );
    const text = JSON.parse(document.querySelector("pre")!.textContent!);
    expect(text.beforeAutomaticReload).toEqual(previous);
  });

  it("keeps the original diagnostic through repeated manual refreshes", async () => {
    entry.dispatchEvent(new Event("error"));
    await vi.advanceTimersByTimeAsync(0);
    const previous = readChunkDiagnostic();
    expect(previous?.automaticReloadAttempted).toBe(true);
    vi.mocked(reloadAfterChunkError).mockImplementation((persist) => {
      persist?.({ reason: "limit-reached", attempts: 2, maxAttempts: 2 });
      return false;
    });

    for (let refresh = 0; refresh < 3; refresh += 1) {
      stop();
      document.body.innerHTML =
        '<div id="root"><div class="qwenpaw-boot"><div class="qwenpaw-boot__content">Loading Console</div></div></div>';
      stop = installStartupMonitor(translations);
      entry.dispatchEvent(new Event("error"));
      await vi.advanceTimersByTimeAsync(0);
      const text = JSON.parse(document.querySelector("pre")!.textContent!);
      expect(text.beforeAutomaticReload).toEqual(previous);
      expect(readChunkDiagnostic()?.automaticReloadAttempted).toBe(false);
      expect(text.current.automaticReload).toEqual({
        reason: "limit-reached",
        attempts: 2,
        maxAttempts: 2,
      });
      document.querySelector("button")!.click();
      await vi.advanceTimersByTimeAsync(0);
      expect(
        JSON.parse(vi.mocked(copyText).mock.calls[refresh][0])
          .beforeAutomaticReload,
      ).toEqual(previous);
    }
  });

  it("copies redacted diagnostics and reports clipboard success", async () => {
    entry.src = `${location.origin}/assets/entry.js?token=secret#secret`;
    entry.dispatchEvent(new Event("error"));
    await vi.advanceTimersByTimeAsync(0);
    document.querySelector("button")!.click();
    await vi.advanceTimersByTimeAsync(0);
    expect(copyText).toHaveBeenCalledOnce();
    expect(vi.mocked(copyText).mock.calls[0][0]).not.toContain("secret");
    expect(document.querySelector("button")!.textContent).toBe(
      en.chunkError.copied,
    );
  });

  it("retains details and manual recovery if copying fails", async () => {
    vi.mocked(copyText).mockRejectedValueOnce(new Error("Clipboard denied"));
    window.dispatchEvent(
      new ErrorEvent("error", { error: new Error("Startup failed") }),
    );
    document.querySelector("button")!.click();
    await vi.advanceTimersByTimeAsync(0);
    expect(document.body.textContent).toContain(en.chunkError.copyFailed);
    expect(document.querySelector("pre")).toBeTruthy();
  });

  it("ignores image loading errors and duplicate entry failure events", async () => {
    const image = document.createElement("img");
    document.body.append(image);
    image.dispatchEvent(new Event("error"));
    expect(readChunkDiagnostic()).toBeNull();
    entry.dispatchEvent(new Event("error"));
    entry.dispatchEvent(new Event("error"));
    await vi.advanceTimersByTimeAsync(0);
    expect(reloadAfterChunkError).toHaveBeenCalledOnce();
  });

  it("recovers manually when session storage is blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("Blocked");
    });
    window.dispatchEvent(
      new ErrorEvent("error", { error: new Error("Startup failed") }),
    );
    expect(document.body.textContent).toContain(en.chunkError.startup.title);
    expect(document.querySelectorAll("button")).toHaveLength(2);
  });

  it("discovers the build even when the entry script is parsed after the monitor", () => {
    stop();
    entry.remove();
    stop = installStartupMonitor(translations);
    document.head.append(entry);
    entry.dispatchEvent(new Event("error"));
    expect(readChunkDiagnostic()?.frontendBuild).toBe(entry.src);
  });

  it.each(Object.keys(translations) as (keyof typeof translations)[])(
    "renders all startup messages and actions in %s",
    (language) => {
      stop();
      localStorage.setItem("language", language);
      stop = installStartupMonitor(translations);
      window.dispatchEvent(
        new ErrorEvent("error", { error: new Error("Startup failed") }),
      );
      expect(document.querySelector("h1")!.textContent).toBe(
        translations[language].startup.title,
      );
      expect(document.querySelector("button")!.textContent).toBe(
        translations[language].copy,
      );
      expect(Object.keys(translations[language].startup)).toEqual(
        Object.keys(en.chunkError.startup),
      );
    },
  );
});

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface BootWatchdogHandle {
  disarm: () => void;
}

interface FakeWindow {
  __qwenpawBootWatchdog?: BootWatchdogHandle;
  __qwenpawBooted?: boolean;
  location: { reload: ReturnType<typeof vi.fn>; href: string };
  addEventListener: (
    type: string,
    handler: (event: unknown) => void,
    capture?: boolean,
  ) => void;
  removeEventListener: (
    type: string,
    handler: (event: unknown) => void,
    capture?: boolean,
  ) => void;
}

const watchdogSource = readFileSync(
  join(process.cwd(), "public", "bootWatchdog.js"),
  "utf8",
);

const RETRY_KEY = "qwenpaw:boot-retries";

function splashMarkup(): string {
  return `
    <div id="root">
      <div class="qwenpaw-boot" role="status" aria-live="polite">
        <div class="qwenpaw-boot__content">
          <img class="qwenpaw-boot__logo" src="/qwenpaw.png" alt="QwenPaw" />
          <span class="qwenpaw-boot__label">Loading Console</span>
        </div>
      </div>
    </div>
  `;
}

/**
 * Run the real shipped script against a controllable window. jsdom marks
 * window.location as [LegacyUnforgeable], so reload cannot be spied on the
 * real window; the script's globals are injected instead (the IIFE only
 * touches window/document/sessionStorage and the timer functions).
 */
function loadWatchdog(options?: {
  window?: FakeWindow;
  markup?: string;
  keepStorage?: boolean;
}): {
  fakeWindow: FakeWindow;
  handle: BootWatchdogHandle;
  emit: (type: string, event: unknown) => void;
} {
  document.body.innerHTML = options?.markup ?? splashMarkup();
  if (!options?.keepStorage) {
    sessionStorage.clear();
  }

  const listeners = new Map<string, Array<(event: unknown) => void>>();
  const fakeWindow: FakeWindow = options?.window ?? {
    location: { reload: vi.fn(), href: "http://localhost/" },
    addEventListener(type, handler) {
      const bucket = listeners.get(type) ?? [];
      bucket.push(handler);
      listeners.set(type, bucket);
    },
    removeEventListener(type, handler) {
      const bucket = listeners.get(type) ?? [];
      const index = bucket.indexOf(handler);
      if (index >= 0) bucket.splice(index, 1);
    },
  };

  new Function(
    "window",
    "document",
    "sessionStorage",
    "setTimeout",
    "clearTimeout",
    watchdogSource,
  )(fakeWindow, document, sessionStorage, setTimeout, clearTimeout);

  const handle = fakeWindow.__qwenpawBootWatchdog;
  expect(handle).toBeDefined();
  if (!handle) throw new Error("boot watchdog handle missing");

  const emit = (type: string, event: unknown) => {
    for (const handler of listeners.get(type) ?? []) handler(event);
  };
  return { fakeWindow, handle, emit };
}

function errorSurface(): HTMLElement | null {
  return document.getElementById("qwenpaw-boot-error");
}

function reloadButton(): HTMLButtonElement | null {
  return document.querySelector<HTMLButtonElement>(".qwenpaw-boot__reload");
}

describe("boot watchdog", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("is loaded from index.html before the module entry", () => {
    const html = readFileSync(join(process.cwd(), "index.html"), "utf8");
    const watchdogIndex = html.indexOf('<script src="/bootWatchdog.js">');
    const entryIndex = html.indexOf("/src/main.tsx");
    expect(watchdogIndex).toBeGreaterThanOrEqual(0);
    expect(entryIndex).toBeGreaterThan(watchdogIndex);
  });

  it("does not surface anything while booting normally", () => {
    const { fakeWindow, emit } = loadWatchdog();
    emit("error", { target: { tagName: "IMG" } });
    expect(errorSurface()).toBeNull();
    expect(fakeWindow.location.reload).not.toHaveBeenCalled();
  });

  it("surfaces an error UI when the entry script fails to load", () => {
    const { emit } = loadWatchdog();
    // The first failure auto-reloads; a persistent failure surfaces the UI.
    emit("error", { target: { tagName: "SCRIPT", src: "/assets/index.js" } });
    emit("error", { target: { tagName: "SCRIPT", src: "/assets/index.js" } });
    const surface = errorSurface();
    expect(surface).not.toBeNull();
    expect(surface).toHaveClass("qwenpaw-boot__error");
    expect(reloadButton()).not.toBeNull();
    expect(
      document.querySelector(".qwenpaw-boot__error-title")?.textContent,
    ).toBeTruthy();
    expect(
      document.querySelector(".qwenpaw-boot__error-detail")?.textContent,
    ).toContain("/assets/index.js");
    expect(
      (document.querySelector(".qwenpaw-boot__label") as HTMLElement).style
        .display,
    ).toBe("none");
  });

  it("surfaces an error UI on a window runtime error before boot", () => {
    const { fakeWindow, emit } = loadWatchdog();
    const event = {
      target: fakeWindow,
      message: "ReferenceError: x is not defined",
    };
    emit("error", event);
    emit("error", event);
    expect(errorSurface()).not.toBeNull();
  });

  it("surfaces an error UI on an unhandled rejection before boot", () => {
    const { emit } = loadWatchdog();
    const event = {
      target: null,
      reason: "Failed to fetch dynamically imported module",
    };
    emit("unhandledrejection", event);
    emit("unhandledrejection", event);
    expect(errorSurface()).not.toBeNull();
  });

  it("ignores non-script resource failures such as the boot logo", () => {
    const { emit } = loadWatchdog();
    emit("error", { target: { tagName: "IMG" } });
    expect(errorSurface()).toBeNull();
  });

  it("ignores errors after boot", () => {
    const { handle, emit } = loadWatchdog();
    handle.disarm();
    emit("error", { target: { tagName: "SCRIPT" } });
    emit("unhandledrejection", { target: null });
    expect(errorSurface()).toBeNull();
  });

  it("sets the boot flag when disarmed", () => {
    const { fakeWindow, handle } = loadWatchdog();
    handle.disarm();
    expect(fakeWindow.__qwenpawBooted).toBe(true);
  });

  it("auto-reloads once when the boot timeout expires", () => {
    const { fakeWindow } = loadWatchdog();
    vi.advanceTimersByTime(15_000);
    expect(fakeWindow.location.reload).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(RETRY_KEY)).toBe("1");
  });

  it("stops auto-reloading and keeps the error surface on the second timeout", () => {
    const first = loadWatchdog();
    vi.advanceTimersByTime(15_000);
    expect(first.fakeWindow.location.reload).toHaveBeenCalledTimes(1);

    // Simulate the reloaded page failing again (retry budget persists
    // across the reload via sessionStorage).
    const second = loadWatchdog({ keepStorage: true });
    vi.advanceTimersByTime(15_000);
    expect(second.fakeWindow.location.reload).not.toHaveBeenCalled();
    expect(errorSurface()).not.toBeNull();
    expect(reloadButton()).not.toBeNull();
  });

  it("reloads from the manual button even after the budget is spent", () => {
    const { fakeWindow, emit } = loadWatchdog();
    emit("error", { target: { tagName: "SCRIPT", src: "/assets/index.js" } });
    expect(fakeWindow.location.reload).toHaveBeenCalledTimes(1);
    // Second failure with the budget spent: error surface with a button.
    emit("error", { target: { tagName: "SCRIPT", src: "/assets/index.js" } });
    const button = reloadButton();
    expect(button).not.toBeNull();
    button!.click();
    expect(fakeWindow.location.reload).toHaveBeenCalledTimes(2);
  });

  it("clears the retry budget when boot succeeds", () => {
    sessionStorage.setItem(RETRY_KEY, "1");
    const { handle } = loadWatchdog();
    handle.disarm();
    expect(sessionStorage.getItem(RETRY_KEY)).toBeNull();
  });

  it("does not re-arm when evaluated twice on the same page", () => {
    const shared: FakeWindow = {
      location: { reload: vi.fn(), href: "http://localhost/" },
      addEventListener: () => {},
      removeEventListener: () => {},
    };
    loadWatchdog({ window: shared });
    const first = shared.__qwenpawBootWatchdog;
    loadWatchdog({ window: shared });
    const second = shared.__qwenpawBootWatchdog;
    expect(second).toBe(first);
  });

  it("survives a missing splash markup", () => {
    const { emit } = loadWatchdog({ markup: "" });
    emit("error", { target: { tagName: "SCRIPT" } });
    expect(errorSurface()).toBeNull();
    emit("error", { target: { tagName: "SCRIPT" } });
    expect(errorSurface()).not.toBeNull();
  });
});

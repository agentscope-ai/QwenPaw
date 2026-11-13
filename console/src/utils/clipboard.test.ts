/**
 * Tests for clipboard copy helper with secure-context fallback.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("copyText", () => {
  const originalClipboard = navigator.clipboard;
  const originalIsSecureContext = window.isSecureContext;
  const originalExecCommand = document.execCommand;

  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: originalClipboard,
    });
    Object.defineProperty(window, "isSecureContext", {
      configurable: true,
      value: originalIsSecureContext,
    });
    document.execCommand = originalExecCommand;
    vi.restoreAllMocks();
  });

  it("uses clipboard API in a secure context", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    Object.defineProperty(window, "isSecureContext", {
      configurable: true,
      value: true,
    });

    const { copyText } = await import("./clipboard");
    await copyText("hello output");

    expect(writeText).toHaveBeenCalledWith("hello output");
  });

  it("falls back to execCommand when clipboard API is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(window, "isSecureContext", {
      configurable: true,
      value: false,
    });
    const execCommand = vi.fn().mockReturnValue(true);
    document.execCommand = execCommand;

    const { copyText } = await import("./clipboard");
    await copyText("fallback content");

    expect(execCommand).toHaveBeenCalledWith("copy");
  });
});

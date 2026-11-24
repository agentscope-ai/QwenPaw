import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useSessionFavicon } from "./useSessionFavicon";

describe("useSessionFavicon", () => {
  let icon: HTMLLinkElement;

  beforeEach(() => {
    icon = document.createElement("link");
    icon.rel = "icon";
    icon.href = "/console/online.svg";
    icon.type = "image/svg+xml";
    document.head.appendChild(icon);
  });

  afterEach(() => icon.remove());

  function svg() {
    return decodeURIComponent(icon.getAttribute("href")!.split(",")[1]);
  }

  it("shows a green dot for an unread completion and restores the icon once read", () => {
    const { rerender } = renderHook(useSessionFavicon, { initialProps: true });
    expect(svg()).toContain("<path");
    expect(svg()).toContain('fill="#52c41a"');
    rerender(false);
    expect(icon.getAttribute("href")).toBe("/console/online.svg");
  });

  it("restores the original favicon and type on navigation or unmount", () => {
    icon.type = "image/png";
    const { unmount } = renderHook(() => useSessionFavicon(true));
    unmount();
    expect(icon.getAttribute("href")).toBe("/console/online.svg");
    expect(icon.type).toBe("image/png");
  });

  it("creates and removes a temporary favicon when none exists", () => {
    icon.remove();
    const { unmount } = renderHook(() => useSessionFavicon(true));
    expect(document.querySelector('link[rel="icon"]')).not.toBeNull();
    unmount();
    expect(document.querySelector('link[rel="icon"]')).toBeNull();
  });

  it("keeps idle and read sessions on the original icon", () => {
    renderHook(() => useSessionFavicon(false));
    expect(icon.getAttribute("href")).toBe("/console/online.svg");
  });
});

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const openExternalLink = vi.fn();
vi.mock("./openExternalLink", async () => {
  const actual = await vi.importActual<typeof import("./openExternalLink")>(
    "./openExternalLink",
  );
  return {
    ...actual,
    openExternalLink: (...args: unknown[]) => openExternalLink(...args),
  };
});

import { interceptBlankLinkClicks } from "./interceptBlankLinkClicks";

/** Render an anchor into the document body and return it. */
function mountAnchor(attrs: Record<string, string>, text = "link") {
  const anchor = document.createElement("a");
  Object.entries(attrs).forEach(([key, value]) => {
    anchor.setAttribute(key, value);
  });
  anchor.textContent = text;
  document.body.appendChild(anchor);
  return anchor;
}

function clickWith(el: Element, init: MouseEventInit = {}) {
  const event = new MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    button: 0,
    ...init,
  });
  el.dispatchEvent(event);
  return event;
}

describe("interceptBlankLinkClicks", () => {
  let dispose: () => void;

  beforeEach(() => {
    openExternalLink.mockReset();
    dispose = interceptBlankLinkClicks();
  });

  afterEach(() => {
    dispose();
    document.body.innerHTML = "";
  });

  it("opens target=_blank external links via openExternalLink and prevents default", () => {
    const anchor = mountAnchor({
      href: "https://example.com/page",
      target: "_blank",
    });

    const event = clickWith(anchor);

    expect(event.defaultPrevented).toBe(true);
    expect(openExternalLink).toHaveBeenCalledWith("https://example.com/page");
  });

  it("handles clicks on nested children of a _blank anchor", () => {
    const anchor = mountAnchor({
      href: "https://example.com/detail",
      target: "_blank",
    });
    const inner = document.createElement("span");
    inner.textContent = "click me";
    anchor.appendChild(inner);

    const event = clickWith(inner);

    expect(event.defaultPrevented).toBe(true);
    expect(openExternalLink).toHaveBeenCalledWith("https://example.com/detail");
  });

  it("ignores anchors without target=_blank (e.g. SPA navigation)", () => {
    const anchor = mountAnchor({ href: "/console/settings" });

    const event = clickWith(anchor);

    expect(event.defaultPrevented).toBe(false);
    expect(openExternalLink).not.toHaveBeenCalled();
  });

  it("ignores unsupported protocols even with target=_blank", () => {
    const anchor = mountAnchor({
      href: "javascript:alert(1)",
      target: "_blank",
    });

    const event = clickWith(anchor);

    expect(event.defaultPrevented).toBe(false);
    expect(openExternalLink).not.toHaveBeenCalled();
  });

  it("ignores modifier-key clicks", () => {
    const anchor = mountAnchor({
      href: "https://example.com",
      target: "_blank",
    });

    clickWith(anchor, { metaKey: true });

    expect(openExternalLink).not.toHaveBeenCalled();
  });

  it("stops intercepting after disposal", () => {
    dispose();
    const anchor = mountAnchor({
      href: "https://example.com",
      target: "_blank",
    });

    clickWith(anchor);

    expect(openExternalLink).not.toHaveBeenCalled();
  });
});

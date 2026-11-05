import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CHAT_CONTENT_WIDTH_EDGE_BUDGET,
  CHAT_CONTENT_WIDTH_STORAGE_KEY,
} from "../../../utils/chatContentWidth";
import ChatContentWidthHandles from "./ChatContentWidthHandles";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const USER_WIDTH_VAR = "--qwenpaw-chat-user-content-width";
const DISPLAY_WIDTH_VAR = "--qwenpaw-chat-content-display-width";

function mountChatColumn(columnWidth: number) {
  const host = document.createElement("div");
  Object.defineProperty(host, "clientWidth", {
    configurable: true,
    value: columnWidth,
  });
  const scroll = document.createElement("div");
  Object.defineProperty(scroll, "scrollBy", {
    configurable: true,
    value: vi.fn(),
  });
  document.body.appendChild(host);
  const containerRef = { current: host };
  const scrollRef = { current: scroll };
  const view = render(
    <ChatContentWidthHandles
      containerRef={containerRef}
      scrollRef={scrollRef}
    />,
    { container: host },
  );
  return { host, scroll, view, containerRef, scrollRef };
}

function handle(host: HTMLElement, side: "left" | "right") {
  return host.querySelector<HTMLElement>(`[data-side="${side}"]`);
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("ChatContentWidthHandles", () => {
  it("publishes the shipped width axis and shows both handles when the column has spare room", () => {
    const { host } = mountChatColumn(1600);
    expect(host.style.getPropertyValue(DISPLAY_WIDTH_VAR)).toBe("960px");
    expect(host.style.getPropertyValue(USER_WIDTH_VAR)).toBe("");
    expect(handle(host, "left")).toBeInTheDocument();
    expect(handle(host, "right")).toBeInTheDocument();
    expect(screen.getAllByRole("separator")).toHaveLength(2);
  });

  it("stays hidden when the column leaves no spare room", () => {
    const { host } = mountChatColumn(820);
    expect(screen.queryAllByRole("separator")).toHaveLength(0);
    expect(host.style.getPropertyValue(DISPLAY_WIDTH_VAR)).toBe("820px");
  });

  it("drags the right edge outward and persists the clamped width", () => {
    const { host } = mountChatColumn(1600);
    const right = handle(host, "right")!;
    fireEvent.pointerDown(right, { button: 0, clientX: 1000 });
    fireEvent.pointerMove(window, { clientX: 1300 });
    fireEvent.pointerUp(window, { clientX: 1300 });
    expect(localStorage.getItem(CHAT_CONTENT_WIDTH_STORAGE_KEY)).toBe(
      String(1600 - CHAT_CONTENT_WIDTH_EDGE_BUDGET),
    );
    expect(host.style.getPropertyValue(USER_WIDTH_VAR)).toBe(
      `${1600 - CHAT_CONTENT_WIDTH_EDGE_BUDGET}px`,
    );
  });

  it("drags the left edge outward symmetrically", () => {
    const { host } = mountChatColumn(1600);
    const left = handle(host, "left")!;
    fireEvent.pointerDown(left, { button: 0, clientX: 1000 });
    fireEvent.pointerMove(window, { clientX: 900 });
    fireEvent.pointerUp(window, { clientX: 900 });
    expect(localStorage.getItem(CHAT_CONTENT_WIDTH_STORAGE_KEY)).toBe("1160");
    expect(host.style.getPropertyValue(USER_WIDTH_VAR)).toBe("1160px");
  });

  it("does not persist a press without movement", () => {
    const { host } = mountChatColumn(1600);
    const right = handle(host, "right")!;
    fireEvent.pointerDown(right, { button: 0, clientX: 1000 });
    fireEvent.pointerUp(window, { clientX: 1000 });
    expect(localStorage.getItem(CHAT_CONTENT_WIDTH_STORAGE_KEY)).toBeNull();
    expect(host.style.getPropertyValue(DISPLAY_WIDTH_VAR)).toBe("960px");
  });

  it("adjusts the width with keyboard arrows and persists it", () => {
    const { host } = mountChatColumn(1600);
    const right = handle(host, "right")!;
    fireEvent.keyDown(right, { key: "ArrowRight" });
    expect(localStorage.getItem(CHAT_CONTENT_WIDTH_STORAGE_KEY)).toBe("976");
    expect(right.getAttribute("aria-valuenow")).toBe("976");
    fireEvent.keyDown(right, { key: "ArrowLeft" });
    expect(localStorage.getItem(CHAT_CONTENT_WIDTH_STORAGE_KEY)).toBe("960");
  });

  it("restores the shipped default on double click", () => {
    const { host } = mountChatColumn(1600);
    fireEvent.keyDown(handle(host, "right")!, { key: "ArrowRight" });
    expect(localStorage.getItem(CHAT_CONTENT_WIDTH_STORAGE_KEY)).toBe("976");
    fireEvent.doubleClick(handle(host, "right")!);
    expect(localStorage.getItem(CHAT_CONTENT_WIDTH_STORAGE_KEY)).toBeNull();
    expect(host.style.getPropertyValue(USER_WIDTH_VAR)).toBe("");
    expect(host.style.getPropertyValue(DISPLAY_WIDTH_VAR)).toBe("960px");
  });

  it("keeps scrolling the transcript with the wheel over a handle", () => {
    const { host, scroll } = mountChatColumn(1600);
    fireEvent.wheel(handle(host, "right")!, { deltaY: 120 });
    expect(scroll.scrollBy).toHaveBeenCalledWith({ top: 120 });
  });

  it("anchors the gradient glow segment at the pointer height", () => {
    const { host } = mountChatColumn(1600);
    const right = handle(host, "right")!;
    fireEvent.pointerMove(right, { clientX: 1500, clientY: 320 });
    expect(
      right.style.getPropertyValue("--qwenpaw-width-handle-pointer-y"),
    ).toBe("320px");
  });
});

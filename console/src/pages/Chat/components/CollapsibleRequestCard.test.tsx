/**
 * Oversized user messages (e.g. the ~25K /mission controller prompt) must
 * collapse behind a summary; short messages and attachment-only messages
 * pass through untouched.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { count?: number }) =>
      key === "chat.request.charCount" ? `${opts?.count} characters` : key,
  }),
}));

import { CollapsibleRequestCard } from "./CollapsibleRequestCard";
import {
  COLLAPSE_THRESHOLD,
  SUMMARY_LENGTH,
  extractRequestText,
} from "./collapsibleRequest";

function textRequestData(text: string) {
  return {
    input: [
      {
        role: "user",
        type: "message",
        content: [{ type: "text", text }],
      },
    ],
  };
}

const vendorCard = <div data-testid="vendor-card">full bubble</div>;

describe("extractRequestText", () => {
  it("joins text parts across input messages", () => {
    const data = {
      input: [
        { content: [{ type: "text", text: "a" }] },
        { content: [{ type: "text", text: "b" }, { type: "image" }] },
      ],
    };
    expect(extractRequestText(data)).toBe("a\nb");
  });

  it("returns empty string for missing/non-array input", () => {
    expect(extractRequestText(null)).toBe("");
    expect(extractRequestText({})).toBe("");
    expect(extractRequestText({ input: "nope" })).toBe("");
  });
});

describe("CollapsibleRequestCard", () => {
  it("renders children directly for short text", () => {
    render(
      <CollapsibleRequestCard data={textRequestData("hello")}>
        {vendorCard}
      </CollapsibleRequestCard>,
    );
    expect(screen.getByTestId("vendor-card")).toBeTruthy();
    expect(screen.queryByText("chat.request.expand")).toBeNull();
  });

  it("renders children directly when text is exactly at the threshold", () => {
    render(
      <CollapsibleRequestCard data={textRequestData("x".repeat(COLLAPSE_THRESHOLD))}>
        {vendorCard}
      </CollapsibleRequestCard>,
    );
    expect(screen.getByTestId("vendor-card")).toBeTruthy();
  });

  it("collapses oversized text behind a summary", () => {
    const longText = "y".repeat(COLLAPSE_THRESHOLD + 1);
    render(
      <CollapsibleRequestCard data={textRequestData(longText)}>
        {vendorCard}
      </CollapsibleRequestCard>,
    );
    // Collapsed by default: vendor card not mounted, summary shown.
    expect(screen.queryByTestId("vendor-card")).toBeNull();
    expect(
      screen.getByText(`${"y".repeat(SUMMARY_LENGTH)}…`),
    ).toBeTruthy();
    expect(
      screen.getByText(`${COLLAPSE_THRESHOLD + 1} characters`),
    ).toBeTruthy();
    expect(screen.getByText("chat.request.expand")).toBeTruthy();
  });

  it("expands and collapses again on toggle", () => {
    const longText = "z".repeat(COLLAPSE_THRESHOLD + 100);
    render(
      <CollapsibleRequestCard data={textRequestData(longText)}>
        {vendorCard}
      </CollapsibleRequestCard>,
    );
    fireEvent.click(screen.getByText("chat.request.expand"));
    expect(screen.getByTestId("vendor-card")).toBeTruthy();
    expect(screen.getByText("chat.request.collapse")).toBeTruthy();
    fireEvent.click(screen.getByText("chat.request.collapse"));
    expect(screen.queryByTestId("vendor-card")).toBeNull();
  });

  it("does not collapse attachment-only messages (no text)", () => {
    const data = {
      input: [
        {
          role: "user",
          content: [{ type: "image", image_url: "x.png" }],
        },
      ],
    };
    render(
      <CollapsibleRequestCard data={data}>
        {vendorCard}
      </CollapsibleRequestCard>,
    );
    expect(screen.getByTestId("vendor-card")).toBeTruthy();
    expect(screen.queryByText("chat.request.expand")).toBeNull();
  });
});

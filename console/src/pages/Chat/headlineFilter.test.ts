import { describe, expect, it } from "vitest";

import {
  createHeadlineFilterState,
  filterHeadlineDelta,
  flushHeadlineFilter,
  stripScrollHeadlineTextBlocks,
} from "./headlineFilter";

function filterChunks(chunks: string[]): string[] {
  const state = createHeadlineFilterState();
  const output = chunks.map((chunk) => filterHeadlineDelta(chunk, state));
  output.push(flushHeadlineFilter(state));
  return output;
}

describe("headline stream filter", () => {
  it("flushes an ordinary HTML comment as soon as it stops matching", () => {
    const output = filterChunks([
      "<!--",
      " ordinary comment -->",
      "normal response",
    ]);

    expect(output).toEqual([
      "",
      "<!-- ordinary comment -->",
      "normal response",
      "",
    ]);
  });

  it("preserves an ordinary comment across every chunk boundary", () => {
    const text = "before<!-- ordinary comment -->after";
    for (let index = 1; index < text.length; index += 1) {
      expect(
        filterChunks([text.slice(0, index), text.slice(index)]).join(""),
      ).toBe(text);
    }
  });

  it("suppresses a real headline across every chunk boundary", () => {
    const headline = "<!--  ⟦ hidden headline ⟧ -->";
    for (let index = 1; index < headline.length; index += 1) {
      const output = filterChunks([
        `before${headline.slice(0, index)}`,
        `${headline.slice(index)}after`,
      ]).join("");
      expect(output).toBe("beforeafter");
    }
  });

  it.each(["<", "<!", "<!--", "<!--  "])(
    "flushes a literal trailing prefix %j at end of stream",
    (prefix) => {
      expect(filterChunks([`ordinary${prefix}`]).join("")).toBe(
        `ordinary${prefix}`,
      );
    },
  );

  it("drops an incomplete headline when the stream ends", () => {
    expect(filterChunks(["visible<!-- ⟦ incomplete headline"]).join("")).toBe(
      "visible",
    );
  });

  it("strips completed text without consuming nested deltas", () => {
    const payload = {
      nested: {
        delta: "<!-- ⟦ streamed headline remains for its own stream ⟧ -->",
        content: {
          type: "text",
          text: "visible\n<!-- ⟦ completed headline is removed ⟧ -->",
        },
      },
    };

    stripScrollHeadlineTextBlocks(payload);

    expect(payload.nested.delta).toContain("streamed headline remains");
    expect(payload.nested.content.text).toBe("visible");
  });
});

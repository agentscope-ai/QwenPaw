import { describe, expect, it } from "vitest";
import type { Message } from "../../../api";
import {
  collectOriginalIds,
  historyPageFromMessages,
  messageOriginalId,
  oldestSourceOriginalId,
  restoreScrollAfterPrepend,
  takeUniqueOlderMessages,
} from "./historyWindow";

function msg(originalId: string | undefined, text: string): Message {
  return {
    role: "assistant",
    content: [{ type: "text", text }],
    metadata: originalId ? { original_id: originalId } : {},
  };
}

describe("messageOriginalId", () => {
  it("reads metadata.original_id", () => {
    expect(messageOriginalId(msg("abc", "x"))).toBe("abc");
  });

  it("returns null when missing or non-string", () => {
    expect(messageOriginalId(msg(undefined, "x"))).toBeNull();
    expect(
      messageOriginalId({
        role: "user",
        content: [],
        metadata: { original_id: 12 },
      }),
    ).toBeNull();
  });
});

describe("oldestSourceOriginalId / collectOriginalIds", () => {
  it("skips messages without original_id and keeps group identity", () => {
    const messages = [
      msg(undefined, "skip"),
      msg("g1", "a"),
      msg("g1", "b"),
      msg("g2", "c"),
    ];
    expect(oldestSourceOriginalId(messages)).toBe("g1");
    expect(collectOriginalIds(messages)).toEqual(["g1", "g2"]);
  });
});

describe("takeUniqueOlderMessages", () => {
  it("drops whole original_id groups that are already loaded", () => {
    const older = [
      msg("g0", "old"),
      msg("g1", "seg-a"),
      msg("g1", "seg-b"),
      msg("g2", "new"),
    ];
    const unique = takeUniqueOlderMessages(older, ["g1"]);
    expect(unique.map((m) => messageOriginalId(m))).toEqual(["g0", "g2"]);
  });

  it("keeps a page with no overlap intact", () => {
    const older = [msg("g0", "a"), msg("g1", "b")];
    expect(takeUniqueOlderMessages(older, ["g2"]).length).toBe(2);
  });
});

describe("historyPageFromMessages", () => {
  it("records has_more, total, and the oldest cursor", () => {
    const page = historyPageFromMessages(
      [msg("old", "a"), msg("new", "b")],
      true,
      40,
    );
    expect(page).toMatchObject({
      hasMore: true,
      total: 40,
      oldestOriginalId: "old",
      loadedOriginalIds: ["old", "new"],
    });
  });
});

describe("restoreScrollAfterPrepend", () => {
  it("keeps reverse-list scrollTop unchanged", () => {
    expect(
      restoreScrollAfterPrepend(
        { scrollTop: -700, scrollHeight: 2000 },
        -700,
        1200,
      ),
    ).toBe(-700);
  });

  it("shifts a top-origin list by the height delta", () => {
    expect(
      restoreScrollAfterPrepend(
        { scrollTop: 80, scrollHeight: 1600 },
        80,
        800,
      ),
    ).toBe(880);
  });
});

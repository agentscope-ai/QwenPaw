import { describe, expect, it } from "vitest";

import type { ProjectSettingsDocument } from "@/contracts/creator";
import {
  diffSubtitleStyleDraft,
  subtitleStyleBaseFrom,
  subtitleStyleDraftDirtyCount,
  subtitleStyleDraftRequests,
  subtitleStyleFromSettings,
} from "../subtitleStyleDraft";

function settings(
  overrides: Partial<ProjectSettingsDocument> = {},
): ProjectSettingsDocument {
  return {
    aspect_ratio: "9:16",
    resolution: "1080x1920",
    content_type: "short_video",
    ...overrides,
  } as ProjectSettingsDocument;
}

const base = (
  settingsOverrides: Partial<ProjectSettingsDocument> = {},
  animation = null,
) => subtitleStyleBaseFrom(settings(settingsOverrides), animation);

describe("subtitleStyleBaseFrom", () => {
  it("starts from what the project actually plays", () => {
    expect(
      base({
        subtitle_template: "variety_pop",
        subtitle_style: {
          color: "#FFE066",
          font_scale: null,
          stroke_scale: 0,
          background_opacity: 0.3,
        },
      }),
    ).toEqual({
      packId: "variety_pop",
      style: {
        color: "#FFE066",
        fontFamily: null,
        fontScale: null,
        strokeScale: 0,
        backgroundOpacity: 0.3,
      },
      animation: null,
    });
  });

  it("reads an untouched project as no overrides at all", () => {
    const live = base();
    expect(live.packId).toBeNull();
    expect(subtitleStyleFromSettings(settings())).toBeNull();
  });
});

describe("diffSubtitleStyleDraft", () => {
  it("sees nothing pending while the draft equals the live style", () => {
    const live = base({ subtitle_template: "variety_pop" });
    expect(diffSubtitleStyleDraft({ ...live }, live)).toEqual({
      pack: false,
      style: false,
      animation: false,
    });
    expect(subtitleStyleDraftDirtyCount({ ...live }, live)).toBe(0);
  });

  it("counts each group once, however many pills it moved", () => {
    const live = base();
    const draft = {
      packId: "cinematic",
      style: { color: "#FFE066", fontScale: 1.25, strokeScale: null },
      animation: { entrance: "pop" as const, loop: true },
    };
    expect(subtitleStyleDraftDirtyCount(draft, live)).toBe(3);
  });

  it("treats an all-default override object as no override", () => {
    const live = base({ subtitle_style: { color: "#FFE066" } });
    expect(diffSubtitleStyleDraft({ ...live, style: null }, live).style).toBe(
      true,
    );
    const clean = base();
    expect(
      diffSubtitleStyleDraft(
        {
          ...clean,
          style: {
            color: null,
            fontScale: null,
            strokeScale: null,
            backgroundOpacity: null,
          },
        },
        clean,
      ).style,
    ).toBe(false);
  });

  it("sees a plate-opacity pick as a style change, 跟随风格 as none", () => {
    // 0 is a stated wish (drop the block), so it has to be pending; leaving
    // the field out means "the pack's own alpha" and never is.
    const live = base({ subtitle_template: "clean_talk" });
    expect(
      diffSubtitleStyleDraft({ ...live, style: { backgroundOpacity: 0 } }, live)
        .style,
    ).toBe(true);
    expect(diffSubtitleStyleDraft({ ...live, style: {} }, live).style).toBe(
      false,
    );
    expect(
      subtitleStyleDraftRequests(
        { ...live, style: { backgroundOpacity: 0.5 } },
        live,
      ),
    ).toEqual([{ subtitleStyle: { backgroundOpacity: 0.5 } }]);
  });

  it("counts going back to smart recommend as a change", () => {
    const live = base({ subtitle_template: "cinematic" });
    expect(diffSubtitleStyleDraft({ ...live, packId: null }, live).pack).toBe(
      true,
    );
  });

  it("never reads an unset motion field as a change", () => {
    // "Follow the style pack" has no token to send, so a draft that leaves a
    // field out cannot be pending on it.
    const live = base({}, { entrance: "pop", exit: "none", loop: false });
    expect(
      diffSubtitleStyleDraft({ ...live, animation: { loop: false } }, live)
        .animation,
    ).toBe(false);
    expect(
      diffSubtitleStyleDraft({ ...live, animation: { loop: true } }, live)
        .animation,
    ).toBe(true);
  });

  it("goes clean once a partial motion pick has landed", () => {
    // The renderer stamps every field it resolved, so the live triple after a
    // successful pick is fuller than the override that was sent; comparing
    // them field by field would keep the confirm button alive forever.
    const before = base({ subtitle_template: "variety_pop" }, null);
    const draft = { ...before, animation: { loop: true } };
    expect(diffSubtitleStyleDraft(draft, before).animation).toBe(true);

    const after = base(
      { subtitle_template: "variety_pop" },
      { entrance: "pop", exit: "none", loop: true },
    );
    expect(diffSubtitleStyleDraft(draft, after).animation).toBe(false);
    expect(subtitleStyleDraftRequests(draft, after, ["cap-1"])).toEqual([]);
  });
});

describe("subtitleStyleDraftRequests", () => {
  it("sends nothing for a draft that only repeats the live style", () => {
    const live = base({ subtitle_template: "cinematic" });
    expect(subtitleStyleDraftRequests({ ...live }, live, ["cap-1"])).toEqual(
      [],
    );
  });

  it("keeps a pack pick project-wide, with no element ids", () => {
    const live = base();
    expect(
      subtitleStyleDraftRequests({ ...live, packId: "variety_pop" }, live, [
        "cap-1",
      ]),
    ).toEqual([{ subtitleTemplate: "variety_pop" }]);
  });

  it("clears the pack with an explicit null", () => {
    const live = base({ subtitle_template: "variety_pop" });
    expect(subtitleStyleDraftRequests({ ...live, packId: null }, live)).toEqual(
      [{ subtitleTemplate: null }],
    );
  });

  it("merges pack and overrides into one project-wide call", () => {
    const live = base();
    expect(
      subtitleStyleDraftRequests(
        { ...live, packId: "cinematic", style: { color: "#FFE066" } },
        live,
        ["cap-1"],
      ),
    ).toEqual([
      {
        subtitleTemplate: "cinematic",
        subtitleStyle: { color: "#FFE066" },
      },
    ]);
  });

  it("addresses only the open caption with a motion pick", () => {
    const live = base();
    expect(
      subtitleStyleDraftRequests(
        { ...live, animation: { entrance: "pop" } },
        live,
        ["cap-1"],
      ),
    ).toEqual([{ animation: { entrance: "pop" }, elementIds: ["cap-1"] }]);
    // Outside a detail view the same pick reaches every subtitle.
    expect(
      subtitleStyleDraftRequests(
        { ...live, animation: { entrance: "pop" } },
        live,
      ),
    ).toEqual([{ animation: { entrance: "pop" } }]);
  });

  it("splits a mixed draft into two calls, pack first", () => {
    // The route rejects a pack addressed at single captions, and the motion
    // override only makes sense after the pack redrew the documents.
    const live = base();
    expect(
      subtitleStyleDraftRequests(
        { ...live, packId: "variety_pop", animation: { entrance: "slide" } },
        live,
        ["cap-1"],
      ),
    ).toEqual([
      { subtitleTemplate: "variety_pop" },
      { animation: { entrance: "slide" }, elementIds: ["cap-1"] },
    ]);
  });
});

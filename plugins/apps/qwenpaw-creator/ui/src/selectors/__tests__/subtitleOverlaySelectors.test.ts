import { describe, expect, it } from "vitest";
import type { OverlayCreationDocument } from "@/contracts/creator";
import {
  isPetContent,
  isSubtitleOverlay,
} from "@/selectors/timelineElementSelectors";

function overlay(
  overrides: Partial<OverlayCreationDocument>,
): OverlayCreationDocument {
  return {
    type: "overlay",
    text: "",
    vibe: "chill",
    prompt: "",
    reference_version_ids: [],
    ...overrides,
  };
}

describe("isSubtitleOverlay", () => {
  // The toolbar count has to match the predicate the backend toggle applies,
  // or the button advertises subtitles it never touches.
  it("treats a declared caption role as a subtitle anywhere", () => {
    expect(
      isSubtitleOverlay(
        overlay({ text: "这句要烧进成片", caption_role: "dialogue" }),
        "pet_video",
      ),
    ).toBe(true);
  });

  it("never counts a text-free decoration", () => {
    expect(
      isSubtitleOverlay(
        overlay({ caption_role: "dialogue", prompt: "装饰动效" }),
        "short_drama",
      ),
    ).toBe(false);
  });

  // The prompts leave a pet-OS bubble roleless on purpose and give it a
  // dedicated layout, so bulk subtitle work must not claim it.
  it("excludes the roleless pet-OS bubble under both spellings", () => {
    expect(
      isSubtitleOverlay(overlay({ text: "本喵要发光" }), "pet_video"),
    ).toBe(false);
    expect(isSubtitleOverlay(overlay({ text: "本喵要发光" }), "pets")).toBe(
      false,
    );
    expect(isPetContent("pet_video") && isPetContent("pets")).toBe(true);
    expect(isPetContent("short_drama")).toBe(false);
  });

  // A migrated interview summary keeps its vibe tag but stays a subtitle.
  it("keeps a pet-project summary card a subtitle", () => {
    expect(
      isSubtitleOverlay(
        overlay({ text: "五年增长了十二倍", vibe: "summary" }),
        "pets",
      ),
    ).toBe(true);
  });

  it("keeps ordinary dramatic copy a subtitle", () => {
    expect(
      isSubtitleOverlay(overlay({ text: "那句台词" }), "short_drama"),
    ).toBe(true);
  });
});

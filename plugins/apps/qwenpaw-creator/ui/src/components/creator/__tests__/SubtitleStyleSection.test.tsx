import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type {
  MotionGraphicDocument,
  ProjectSettingsDocument,
  SubtitleStyleUpdateRequest,
} from "@/contracts/creator";
import SubtitleStyleSection, {
  captionDocumentOwnedByStyle,
  subtitleAnimationFromDocument,
  subtitleStyleFromSettings,
  type SubtitleStyleDraft,
} from "../SubtitleStyleSection";
import { subtitleStyleBaseFrom } from "../subtitleStyleDraft";

function settings(
  overrides: Partial<ProjectSettingsDocument> = {},
): ProjectSettingsDocument {
  return {
    aspect_ratio: "9:16",
    resolution: "1080x1920",
    platform: "douyin",
    language: "zh",
    target_duration_seconds: 30,
    content_type: "short_video",
    ...overrides,
  } as ProjectSettingsDocument;
}

interface SectionProps {
  settings?: Partial<ProjectSettingsDocument>;
  /** What the caption document plays today; ``undefined`` = pack default. */
  animation?: SubtitleStyleDraft["animation"];
  motionOwned?: boolean;
  elementScoped?: boolean;
  busy?: boolean;
  /** The bar hides the motion picker unless a test asks for it back. */
  showMotion?: boolean;
}

/**
 * The bar is a controlled draft, so the test needs the owner the detail panel
 * is: state that the pickers write into.  The bar no longer holds a write
 * path at all — only the panel's 「应用修改」 sends the diff — so the tests
 * read the draft and the 「当前生效」 line, never a request.
 */
function renderSection(props: SectionProps = {}) {
  const live = subtitleStyleBaseFrom(
    settings(props.settings),
    props.animation ?? null,
  );
  let latestDraft: SubtitleStyleDraft = live;

  function Harness() {
    const [draft, setDraft] = useState<SubtitleStyleDraft>(live);
    return (
      <SubtitleStyleSection
        settings={settings(props.settings)}
        base={live}
        draft={draft}
        onDraftChange={(next) => {
          latestDraft = next;
          setDraft(next);
        }}
        motionOwned={props.motionOwned}
        elementScoped={props.elementScoped}
        busy={props.busy}
        showMotion={props.showMotion}
      />
    );
  }

  render(<Harness />);
  return {
    draft: () => latestDraft,
  };
}

describe("SubtitleStyleSection", () => {
  it("names the style that is actually in effect", () => {
    render(
      <SubtitleStyleSection
        settings={settings({ subtitle_template: "variety_pop" })}
        base={subtitleStyleBaseFrom(
          settings({ subtitle_template: "variety_pop" }),
          null,
        )}
        draft={subtitleStyleBaseFrom(
          settings({ subtitle_template: "variety_pop" }),
          null,
        )}
        onDraftChange={vi.fn()}
      />,
    );
    expect(screen.getByText("当前生效：综艺花字")).toBeInTheDocument();
  });

  it("says smart recommend while the project never picked a pack", () => {
    renderSection();
    expect(screen.getByText("当前生效：智能推荐")).toBeInTheDocument();
  });

  it("keeps a pack pick local instead of rewriting every caption at once", async () => {
    const user = userEvent.setup();
    const view = renderSection();

    await user.click(screen.getByRole("button", { name: /综艺花字/ }));

    // The old behaviour: one click PATCHed the project, redrew every caption
    // document and invalidated the composed master. A browse must be free,
    // and the bar no longer even holds a write path to do it with.
    expect(view.draft()).toMatchObject({ packId: "variety_pop" });
    // And the bar still tells the truth about what is playing right now.
    expect(screen.getByText("当前生效：智能推荐")).toBeInTheDocument();
  });

  it("counts the pending groups so the confirm button can carry them", async () => {
    const user = userEvent.setup();
    renderSection({ settings: { subtitle_template: "variety_pop" } });

    expect(screen.queryByText(/字幕风格改动待确认/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /电影叙事/ }));
    await user.click(screen.getByLabelText("#FFE066"));

    const pending = await waitFor(() => screen.getByText(/字幕风格改动待确认/));
    expect(pending.textContent).toContain("2");
  });

  it("drops the pending count back to nothing when the pick is undone", async () => {
    const user = userEvent.setup();
    renderSection({ settings: { subtitle_template: "variety_pop" } });

    await user.click(screen.getByRole("button", { name: /电影叙事/ }));
    expect(screen.getByText(/字幕风格改动待确认/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /综艺花字/ }));
    expect(screen.queryByText(/字幕风格改动待确认/)).not.toBeInTheDocument();
  });

  it("keeps a colour override in the draft too", async () => {
    const user = userEvent.setup();
    const view = renderSection();

    await user.click(screen.getByLabelText("#FFE066"));

    expect(view.draft().style).toEqual({
      color: "#FFE066",
      fontFamily: null,
      fontScale: null,
      strokeScale: null,
      backgroundOpacity: null,
    });
  });

  it("holds a motion pick for the confirm button as well", async () => {
    const user = userEvent.setup();
    const view = renderSection({ elementScoped: true, showMotion: true });

    await user.click(screen.getByText("弹入"));

    expect(view.draft().animation).toEqual({ entrance: "pop" });
  });

  it("echoes the draft back into the pills, not the persisted setting", async () => {
    const user = userEvent.setup();
    renderSection({
      settings: {
        subtitle_template: "cinematic",
        subtitle_style: { color: "#7DD3FC", font_scale: 1.25, stroke_scale: 0 },
      },
      animation: { entrance: "slide", exit: "soft_fade", loop: true },
      showMotion: true,
    });

    expect(screen.getByLabelText("#7DD3FC")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("滑入")).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByText("弹入"));
    expect(screen.getByText("弹入")).toHaveAttribute("aria-pressed", "true");
    // The pack default hint is gone as soon as a motion is stated.
    expect(
      screen.queryByText("未选择时跟随风格包默认动效"),
    ).not.toBeInTheDocument();
  });

  it("tells the user the motion picker only reaches this caption", () => {
    renderSection({ elementScoped: true, showMotion: true });
    expect(
      screen.getByText("动效只改这条字幕；风格包与样式作用于全项目字幕"),
    ).toBeInTheDocument();
  });

  it("offers no button of its own to write the picks", () => {
    // The 「按所选风格同步动效描述」 button is gone: the panel's 应用修改
    // already syncs descriptions and redraws documents on every pack or style
    // switch (the route's syncPrompts defaults to true), so a second button
    // only differed by demanding no change at all — and two write buttons in
    // one panel is how a browse stops being free.
    renderSection();
    expect(
      screen.queryByRole("button", { name: /同步动效描述/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /应用修改/ }),
    ).not.toBeInTheDocument();
  });

  it("goes inert while a request is in flight", async () => {
    const user = userEvent.setup();
    const view = renderSection({ busy: true, showMotion: true });

    await user.click(screen.getByText("弹入"));

    expect(view.draft().animation).toBeNull();
  });

  it("trades the motion picker for an explanation when the design owns the look", () => {
    renderSection({ motionOwned: false, showMotion: true });

    expect(
      screen.getByText(
        "这条字幕的外观由其动效设计决定，风格包不会重写它；入场/出场/循环请在动效设计里调整",
      ),
    ).toBeInTheDocument();
    // A picker whose choice the route would refuse is worse than no picker.
    expect(screen.queryByText("弹入")).not.toBeInTheDocument();
  });

  it("keeps the picker for a caption that has no document yet", () => {
    // compose falls back to the pack there, so the pick does land.
    renderSection({ motionOwned: true, showMotion: true });
    expect(screen.getByText("弹入")).toBeInTheDocument();
  });

  it("offers no motion picker while the renderer is offline", () => {
    // The default is the shipped state: an entrance pill the composed master
    // cannot honour is the "my setting did nothing" report, so the picker
    // stays out of the bar until someone asks for it back.
    renderSection();
    expect(screen.queryByText("字幕动效")).not.toBeInTheDocument();
    expect(screen.queryByText("弹入")).not.toBeInTheDocument();
  });

  it("keeps the motion sentences out of the bar too", () => {
    // Sentences about a control the bar no longer offers would leave the user
    // looking for a picker that was never there.
    renderSection({ motionOwned: false, elementScoped: true });
    expect(
      screen.queryByText(
        "这条字幕的外观由其动效设计决定，风格包不会重写它；入场/出场/循环请在动效设计里调整",
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("动效只改这条字幕；风格包与样式作用于全项目字幕"),
    ).not.toBeInTheDocument();
  });

  it("still offers the style controls the motion switch does not cover", () => {
    renderSection();
    expect(
      screen.getByRole("button", { name: /综艺花字/ }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("#FFE066")).toBeInTheDocument();
  });

  it("still sends a project-wide pack with no element ids", () => {
    // The confirm handler builds the requests from the same draft the bar
    // writes, and the route rejects a pack addressed at single captions.
    const requests: SubtitleStyleUpdateRequest[] = [
      { subtitleTemplate: "variety_pop" },
    ];
    expect(requests[0]).not.toHaveProperty("elementIds");
  });
});

describe("subtitleStyleFromSettings", () => {
  it("maps the persisted snake_case overrides onto the control shape", () => {
    expect(
      subtitleStyleFromSettings(
        settings({
          subtitle_style: {
            color: null,
            font_scale: 0.85,
            stroke_scale: null,
            background_opacity: 0.3,
          },
        }),
      ),
    ).toEqual({
      color: null,
      fontFamily: null,
      fontScale: 0.85,
      strokeScale: null,
      backgroundOpacity: 0.3,
    });
  });

  it("reports null for a project that never overrode anything", () => {
    expect(subtitleStyleFromSettings(settings())).toBeNull();
  });
});

describe("captionDocumentOwnedByStyle", () => {
  const doc = (
    overrides: Partial<MotionGraphicDocument>,
  ): MotionGraphicDocument =>
    ({
      format: "html_css",
      motif: "caption_card",
      template_version: 3,
      ...overrides,
    }) as MotionGraphicDocument;

  it("matches the backend rule for derivable captions", () => {
    expect(captionDocumentOwnedByStyle(doc({}))).toBe(true);
    // A legacy document this pipeline never stamped is not derived data.
    expect(captionDocumentOwnedByStyle(doc({ template_version: null }))).toBe(
      false,
    );
    expect(captionDocumentOwnedByStyle(doc({ motif: "custom" }))).toBe(false);
    expect(captionDocumentOwnedByStyle(doc({ format: "html_js" }))).toBe(false);
    expect(captionDocumentOwnedByStyle(undefined)).toBe(false);
  });
});

describe("subtitleAnimationFromDocument", () => {
  const caption = (
    overrides: Partial<MotionGraphicDocument>,
  ): MotionGraphicDocument =>
    ({
      format: "html_css",
      motif: "caption_card",
      fps: 25,
      loop: false,
      design_notes: "",
      ...overrides,
    }) as MotionGraphicDocument;

  it("reads the triple back out of the stamp the renderer wrote", () => {
    expect(
      subtitleAnimationFromDocument(
        caption({
          entrance: "slide",
          exit: "soft_fade",
          design_notes:
            "caption_style=variety_pop|None caption_animation=slide/soft_fade/1",
        }),
      ),
    ).toEqual({ entrance: "slide", exit: "soft_fade", loop: true });
  });

  it("will not light up a pill the renderer cannot play", () => {
    // A token outside the vocabulary can only come from a damaged or future
    // document; reading it back verbatim would show a choice the picker
    // cannot send and the compositor would ignore.
    expect(
      subtitleAnimationFromDocument(
        caption({ design_notes: "caption_animation=bounce/dissolve/1" }),
      ),
    ).toEqual({ entrance: null, exit: null, loop: true });
  });

  it("reports nothing for a document this pipeline never drew", () => {
    expect(
      subtitleAnimationFromDocument(caption({ design_notes: "hand authored" })),
    ).toBeNull();
    expect(subtitleAnimationFromDocument(undefined)).toBeNull();
  });

  it("stays quiet about documents the caption bar does not own", () => {
    expect(
      subtitleAnimationFromDocument(
        caption({
          motif: "custom",
          design_notes: "caption_animation=pop/none/0",
        }),
      ),
    ).toBeNull();
    expect(
      subtitleAnimationFromDocument(
        caption({
          format: "html_js",
          design_notes: "caption_animation=pop/none/0",
        }),
      ),
    ).toBeNull();
  });
});

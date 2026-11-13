import type {
  ProjectSettingsDocument,
  SubtitleAnimationPolicy,
  SubtitleFontFamily,
  SubtitleStyle,
  SubtitleStyleUpdateRequest,
} from "@/contracts/creator";

/**
 * A local, not-yet-sent subtitle style selection.
 *
 * The three pickers in the subtitle style bar describe one thing, so they
 * share a single draft: what the user picked, next to what the project
 * actually plays.  Nothing here talks to the backend — the detail panel's
 * 「确认修改」 button turns the difference between the two into the requests
 * the style endpoint accepts, which is what keeps a stray click from
 * redrawing every caption (and invalidating the composed master) on its own.
 */
export interface SubtitleStyleDraft {
  packId: string | null;
  style: SubtitleStyle | null;
  animation: SubtitleAnimationPolicy | null;
}

/** Which of the three groups the draft actually moved. */
export interface SubtitleStyleDraftDiff {
  pack: boolean;
  style: boolean;
  animation: boolean;
}

/** Map the persisted snake_case overrides onto the control's camel shape. */
export function subtitleStyleFromSettings(
  settings: ProjectSettingsDocument,
): SubtitleStyle | null {
  const stored = settings.subtitle_style;
  if (!stored) return null;
  return {
    color: stored.color ?? null,
    fontScale: stored.font_scale ?? null,
    strokeScale: stored.stroke_scale ?? null,
    backgroundOpacity: stored.background_opacity ?? null,
    fontFamily: (stored.font_family ?? null) as SubtitleFontFamily | null,
  };
}

/** Where the pickers start: the style the project is playing right now. */
export function subtitleStyleBaseFrom(
  settings: ProjectSettingsDocument,
  animation: SubtitleAnimationPolicy | null,
): SubtitleStyleDraft {
  return {
    packId: settings.subtitle_template ?? null,
    style: subtitleStyleFromSettings(settings),
    animation,
  };
}

const blankStyle = (): Required<SubtitleStyle> => ({
  color: null,
  fontScale: null,
  strokeScale: null,
  backgroundOpacity: null,
  fontFamily: null,
});

function styleDiffers(
  draft: SubtitleStyle | null,
  base: SubtitleStyle | null,
): boolean {
  const mine = { ...blankStyle(), ...(draft ?? {}) };
  const live = { ...blankStyle(), ...(base ?? {}) };
  return (
    mine.color !== live.color ||
    mine.fontScale !== live.fontScale ||
    mine.strokeScale !== live.strokeScale ||
    mine.backgroundOpacity !== live.backgroundOpacity ||
    mine.fontFamily !== live.fontFamily
  );
}

/**
 * A draft field left unset means "follow the style pack", so it can never be a
 * change — only a stated choice that contradicts the live document is.  After
 * a pick lands, the renderer stamps every field it resolved; comparing a
 * partial override against that full triple would then read as dirty forever.
 */
function animationDiffers(
  draft: SubtitleAnimationPolicy | null,
  base: SubtitleAnimationPolicy | null,
): boolean {
  const mine = draft ?? {};
  const live = base ?? {};
  return (
    (mine.entrance != null && mine.entrance !== live.entrance) ||
    (mine.exit != null && mine.exit !== live.exit) ||
    (mine.loop != null && mine.loop !== live.loop)
  );
}

export function diffSubtitleStyleDraft(
  draft: SubtitleStyleDraft,
  base: SubtitleStyleDraft,
): SubtitleStyleDraftDiff {
  return {
    pack: draft.packId !== base.packId,
    style: styleDiffers(draft.style, base.style),
    animation: animationDiffers(draft.animation, base.animation),
  };
}

/** How many pending groups the 确认修改 button should count. */
export function subtitleStyleDraftDirtyCount(
  draft: SubtitleStyleDraft,
  base: SubtitleStyleDraft,
): number {
  const diff = diffSubtitleStyleDraft(draft, base);
  return Number(diff.pack) + Number(diff.style) + Number(diff.animation);
}

/**
 * The requests this draft owes the style endpoint, in the order to send them.
 *
 * A style pack and its overrides are project-wide promises while the motion
 * picker may address one caption, and the route refuses to mix the two in one
 * call — so a draft that moved both becomes two calls, pack first: the pack
 * switch redraws the documents to its signature motion and the motion pick
 * then overrides exactly the captions it was aimed at.
 *
 * Only the keys that changed are set, because a present key is authoritative:
 * sending an untouched ``subtitleStyle`` would rewrite the overrides the
 * project already has.
 */
export function subtitleStyleDraftRequests(
  draft: SubtitleStyleDraft,
  base: SubtitleStyleDraft,
  elementIds?: string[],
): SubtitleStyleUpdateRequest[] {
  const diff = diffSubtitleStyleDraft(draft, base);
  const requests: SubtitleStyleUpdateRequest[] = [];
  if (diff.pack || diff.style) {
    const projectWide: SubtitleStyleUpdateRequest = {};
    if (diff.pack) projectWide.subtitleTemplate = draft.packId;
    if (diff.style) projectWide.subtitleStyle = draft.style;
    requests.push(projectWide);
  }
  if (diff.animation) {
    requests.push(
      elementIds?.length
        ? { animation: draft.animation ?? {}, elementIds }
        : { animation: draft.animation ?? {} },
    );
  }
  return requests;
}

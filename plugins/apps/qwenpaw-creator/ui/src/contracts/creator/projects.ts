import type { CreatorSessionStatus } from "./sessions";

export type CreatorScenario = "short_drama" | "video_edit" | "general";

/**
 * Typeface id for the standard subtitle bar. `default`/null keeps the
 * renderer's auto-detected sans CJK face; the rest map to the bundled system
 * faces in the backend `overlay._SUBTITLE_FONT_FAMILIES`.
 */
export type SubtitleFontFamily = "default" | "song" | "hei" | "kai";

/**
 * User overrides for the standard subtitle bar. Every field is optional:
 * `null`/absent keeps the renderer default, so an untouched project looks
 * exactly as before. Applied by the deterministic plain-subtitle renderer
 * and its live preview; designed 花字 keeps its own per-footage styling.
 */
export interface SubtitleStyle {
  /** Solid text colour as `#rrggbb`; null = default white. */
  color?: string | null;
  /** Font-size multiplier (0.6–1.8); null = base size. */
  fontScale?: number | null;
  /** Outline-width multiplier (0–3, 0 = no outline); null = base outline. */
  strokeScale?: number | null;
  /**
   * Opacity (0–1) of the background block a style pack draws behind the text;
   * null = the pack's own, 0 = no block. It reshapes the block a pack already
   * draws and never invents one, so a pack without a block looks unchanged at
   * every value.
   */
  backgroundOpacity?: number | null;
  /** Typeface id; null/`default` = the auto-detected sans CJK face. */
  fontFamily?: SubtitleFontFamily | null;
}

/**
 * Entrance / exit / loop one caption must play. Absent or `null` keeps what
 * the style pack (or the element itself) already chose; the vocabulary is the
 * renderer's own, so a description can never name a motion the pixels skip.
 */
export interface SubtitleAnimationPolicy {
  entrance?: "soft_fade" | "pop" | "slide" | "type_on" | null;
  exit?: "none" | "soft_fade" | "shrink" | null;
  loop?: boolean | null;
}

/**
 * A user-saved bundle of style-window picks: base pack plus whichever
 * colour / size / outline / plate and motion choices were set when it
 * was saved.  Applying one is exactly re-moving those controls.
 */
export interface UserSubtitleStyle {
  styleId: string;
  name: string;
  description?: string;
  packId?: string | null;
  style?: SubtitleStyle;
  animation?: SubtitleAnimationPolicy;
}

export interface UserSubtitleStyleListResponse {
  items: UserSubtitleStyle[];
}

/**
 * Switch the subtitle style pack after the project exists.
 *
 * A key that is present wins: `subtitleTemplate: null` goes back to smart
 * recommend and `subtitleStyle: null` clears the colour/size/outline
 * overrides. The backend keeps the burned-in captions, the live preview and
 * every subtitle's 动效描述 in step with the choice.
 */
export interface SubtitleStyleUpdateRequest {
  subtitleTemplate?: string | null;
  subtitleStyle?: SubtitleStyle | null;
  animation?: SubtitleAnimationPolicy;
  /** Restrict the change to these elements (defaults to every subtitle). */
  elementIds?: string[];
  /** Fill the canonical style sentence into empty descriptions; default true. */
  syncPrompts?: boolean;
}

export interface ProjectCreateRequest {
  productionStage?: "script" | "media";
  clientRequestId: string;
  name: string;
  nameSource?: "user" | "auto";
  description?: string;
  scenario: CreatorScenario;
  aspectRatio: string;
  resolution: string;
  contentType?: string | null;
  templateId?: string;
  subtitlePolicy?: "auto" | "on" | "off";
  /** Optional JianYing-like subtitle style pack id; null = smart recommend. */
  subtitleTemplate?: string | null;
  /** Optional overrides for the standard subtitle bar (colour/size/outline). */
  subtitleStyle?: SubtitleStyle | null;
  /** Optional project-level caption motion default; unset follows the pack. */
  subtitleAnimation?: SubtitleAnimationPolicy | null;
  /** Optional atomic bootstrap goal persisted in the file Runtime aggregate. */
  initialGoal?: string;
}

export interface ProjectCreateResponse {
  projectId: string;
  creatorSessionId: string;
  conversationId: string;
  projectSnapshotId: string;
  header: ProjectCreateHeader;
}

export interface ProjectCreateHeader {
  id: string;
  name: string;
  description: string;
  scenario: CreatorScenario;
  aspectRatio: string;
  resolution: string;
  contentType: string | null;
  subtitleTemplate?: string | null;
  subtitleStyle?: SubtitleStyle | null;
}

export interface ProjectSummary {
  projectId: string;
  name: string;
  description: string;
  scenario: CreatorScenario;
  aspectRatio: string;
  resolution: string;
  contentType?: string | null;
  createdAt: string;
  updatedAt: string;
  /** Version id of the media the backend picked as the project preview. */
  coverVersionId?: string | null;
  /**
   * Which media route serves the cover: the version bytes themselves for
   * images, or an extracted keyframe when only a video exists.
   */
  coverVersionSource?:
    | "artifact"
    | "source"
    | "artifact_frame"
    | "source_frame"
    | null;
  /**
   * Newest rendered final cut, when the Project has one; drives the card
   * preview button on the home page.
   */
  finalVideoVersionId?: string | null;
  /** Current session status, null when no runtime session exists. */
  status?: CreatorSessionStatus | null;
  /**
   * Some Task is QUEUED or RUNNING. The card badge used to derive this from one
   * /tasks request per Project; the listing answers it for the whole page.
   */
  hasActiveTask?: boolean;
}

export interface ProjectListResponse {
  items: ProjectSummary[];
  limit: number;
  offset: number;
}

/** One OSS-hosted inspiration example backed by a built-in Project. */
export interface InspirationExampleSummary {
  id: string;
  title: string;
  description: string;
  projectId: string;
  installed: boolean;
}

export interface InspirationExampleListResponse {
  items: InspirationExampleSummary[];
}

export interface InspirationExampleOpenResponse {
  projectId: string;
  installed: boolean;
}

/** Polled download progress while an example archive streams in from OSS. */
export interface InspirationExampleOpenProgress {
  state: "installed" | "downloading" | "idle";
  receivedBytes?: number;
  totalBytes?: number | null;
}

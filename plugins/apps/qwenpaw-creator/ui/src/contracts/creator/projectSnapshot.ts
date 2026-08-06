/** Canonical Project document from GET /projects/:id/project. */
export type ProjectJsonRecord = Record<string, unknown>;

export interface ProjectEntityCollection<T> {
  items: Record<string, T>;
  order: string[];
}

export interface ProjectSettingsDocument extends ProjectJsonRecord {
  aspect_ratio: string;
  resolution: string;
  platform: string;
  language: string;
  target_duration_seconds: number | null;
  content_type: string | null;
  execution_preauthorization?: ProjectJsonRecord | null;
}

export interface CreativeStrategyDocument extends ProjectJsonRecord {
  creative_brief: string;
  audience: string;
  creative_direction: string;
  constraints: string;
  success_criteria: string;
}

export interface IndexedFileDocument extends ProjectJsonRecord {
  file_id: string;
  kind: string;
  relative_uri: string;
  sha256: string;
  size_bytes: number;
  media_type: string;
  created_at: string;
}

export interface SourceAssetVersionDocument extends ProjectJsonRecord {
  version_id: string;
  logical_asset_id: string;
  name: string;
  file_id: string | null;
  checksum: string;
  media_kind: "image" | "video" | "audio" | "document" | "text" | "other";
  media_type: string;
  provenance_refs: string[];
  thumbnail_file_id: string | null;
  duration_seconds: number | null;
  native_model_file_id: string | null;
  created_at: string;
  metadata: ProjectJsonRecord;
}

export interface SourceIntelligenceVersionDocument extends ProjectJsonRecord {
  intelligence_version_id: string;
  source_asset_version_id: string;
  file_id: string;
  source_checksum: string;
  model_run_ids: string[];
  coverage: Record<string, string>;
  created_at: string;
}

export interface ArtifactSlotDocument extends ProjectJsonRecord {
  slot_id: string;
  kind: string;
  owner_ref: string;
  version_ids: string[];
  selected_version_id: string | null;
  metadata: ProjectJsonRecord;
}

export interface ArtifactVersionDocument extends ProjectJsonRecord {
  version_id: string;
  slot_id: string;
  kind: string;
  owner_ref: string;
  name: string;
  file_id: string;
  checksum: string;
  based_on_generation: number;
  provenance_refs: string[];
  thumbnail_file_id: string | null;
  duration_seconds: number | null;
  input_fingerprint: string | null;
  stale: boolean;
  stale_reason: string | null;
  created_at: string;
  metadata: ProjectJsonRecord;
}

export interface ProjectAssetIndexDocument extends ProjectJsonRecord {
  files_by_id: Record<string, IndexedFileDocument>;
  source_versions_by_id: Record<string, SourceAssetVersionDocument>;
  intelligence_versions_by_id: Record<
    string,
    SourceIntelligenceVersionDocument
  >;
  artifact_slots_by_id: Record<string, ArtifactSlotDocument>;
  artifact_versions_by_id: Record<string, ArtifactVersionDocument>;
}

export interface ProjectSourceDocument extends ProjectJsonRecord {
  source_id: string;
  display_name: string;
  logical_asset_id: string;
  selected_asset_version_id: string;
  current_intelligence_version_id: string | null;
  user_notes: string;
}

export interface ProjectSourceCatalogDocument extends ProjectJsonRecord {
  sources: ProjectEntityCollection<ProjectSourceDocument>;
}

export interface VisualVariantDocument extends ProjectJsonRecord {
  variant_id: string;
  requirements: string;
  prompt: string;
  reference_asset_version_ids: string[];
  reference_artifact_version_ids: string[];
  generated_artifact_version_ids: string[];
  selected_artifact_version_id: string | null;
  derived_from_variant_id?: string | null;
  consistency_tags?: string[];
}

export interface CharacterVoiceDocument extends ProjectJsonRecord {
  voice_id: string;
  target_model: string;
  preferred_name: string;
  sample_source_version_id: string | null;
  enrollment_key: string;
  created_at: string;
}

export interface VisualEntityDocument extends ProjectJsonRecord {
  entity_id: string;
  kind: "character" | "scene" | "prop";
  name: string;
  description: string;
  continuity: string;
  required_variant_ids: string[];
  variants: ProjectEntityCollection<VisualVariantDocument>;
  selected_artifact_version_id: string | null;
  voice?: CharacterVoiceDocument | null;
  canonical_variant_id?: string | null;
}

export interface VisualCastLineupDocument extends ProjectJsonRecord {
  lineup_id: string;
  name: string;
  description: string;
  character_refs: string[];
  scene_ref: string | null;
  prop_refs: string[];
  reference_asset_version_ids: string[];
  reference_artifact_version_ids: string[];
  generated_artifact_version_ids: string[];
  selected_artifact_version_id: string | null;
  relative_notes: string;
}

export interface VisualDevelopmentDocument extends ProjectJsonRecord {
  visual_bible: string;
  style: string;
  entities: ProjectEntityCollection<VisualEntityDocument>;
  cast_lineups?: ProjectEntityCollection<VisualCastLineupDocument>;
}

export interface TimelineSpanDocument extends ProjectJsonRecord {
  start_tick: number;
  duration_tick: number;
}

export interface ElementLocationDocument extends ProjectJsonRecord {
  coordinate_space: "normalized_canvas";
  x: number;
  y: number;
  width: number;
  height: number;
  anchor_x: number;
  anchor_y: number;
  rotation_degrees: number;
  opacity: number;
}

export interface GenerationRecipeDocument extends ProjectJsonRecord {
  provider: string;
  model: string;
  seed: number | null;
  candidate_count: number;
}

export interface ShotDocument extends ProjectJsonRecord {
  shot_id: string;
  description: string;
  camera: string | null;
  framing: string | null;
  duration_seconds: number | null;
  dialogue?: string;
}

export type VideoGenerationMode = "r2v" | "t2v" | "i2v" | "s2v";

export interface R2VCreationDocument extends ProjectJsonRecord {
  type: "r2v";
  intent: string;
  narrative: string;
  continuity: string;
  character_refs: string[];
  scene_ref: string | null;
  prop_refs: string[];
  visual_variant_refs: Record<string, string>;
  cast_lineup_refs?: string[];
  shots: ProjectEntityCollection<ShotDocument>;
  recipe: GenerationRecipeDocument | null;
  storyboard_prompt: string;
  storyboard_reference_version_ids: string[];
  video_prompt: string;
  video_reference_version_ids: string[];
}

export interface T2VCreationDocument extends ProjectJsonRecord {
  type: "t2v";
  intent: string;
  narrative: string;
  continuity: string;
  video_prompt: string;
  recipe: GenerationRecipeDocument | null;
}

export interface I2VCreationDocument extends ProjectJsonRecord {
  type: "i2v";
  intent: string;
  narrative: string;
  continuity: string;
  first_frame_version_id: string | null;
  video_prompt: string;
  recipe: GenerationRecipeDocument | null;
}

export interface S2VCreationDocument extends ProjectJsonRecord {
  type: "s2v";
  intent: string;
  // Visual entity whose portrait (and enrolled voice) drives the clip.
  character_ref: string | null;
  // Exact image version used as the s2v reference portrait.
  portrait_version_id: string | null;
  // Spoken lines; TTS turns them into the driving audio below.
  script: string;
  audio_version_id: string | null;
  recipe: GenerationRecipeDocument | null;
}

export interface EditCreationDocument extends ProjectJsonRecord {
  type: "edit";
  intent: string;
  reason: string;
  original_sound: "preserve";
  source_intelligence_version_id: string | null;
}

export interface MotionGraphicDocument extends ProjectJsonRecord {
  format: "html_css" | "html_js";
  html?: string | null;
  html_file_id?: string | null;
  fps: number;
  loop: boolean;
  design_notes: string;
  motif?: string;
  template_version?: number | null;
  theme?: string;
  variant?: string;
  emotion?: string;
  entrance?: string;
  exit?: string;
  intensity?: number;
}

export interface OverlayCreationDocument extends ProjectJsonRecord {
  type: "overlay";
  // The overlay role derives from data: non-empty text = caption card;
  // empty text with motion/prompt = text-free decoration; media stickers
  // reference their payload through the element's render_source.
  text: string;
  vibe: string;
  prompt: string;
  reference_version_ids: string[];
  motion?: MotionGraphicDocument | null;
}

export interface TransitionCreationDocument extends ProjectJsonRecord {
  type: "transition";
  from_element_id: string;
  to_element_id: string;
  transition_kind: string;
  easing: string;
}

// A full-canvas motion document that carries the segment's whole picture
// (pure motion-graphics cut, no footage behind it).
export interface MotionClipCreationDocument extends ProjectJsonRecord {
  type: "motion_clip";
  intent: string;
  prompt: string;
  motion?: MotionGraphicDocument | null;
}

export interface AudioCreationDocument extends ProjectJsonRecord {
  type: "audio";
  source_asset_version_id: string;
  /** TTS narration keeps its script here; uploaded audio leaves it empty. */
  script?: string;
  /** Synthesis speed multiplier (0.5–2.0); CosyVoice family only. */
  speech_rate?: number;
  gain_db: number;
  pan: number;
}

export type ElementCreationDocument =
  | R2VCreationDocument
  | T2VCreationDocument
  | I2VCreationDocument
  | S2VCreationDocument
  | EditCreationDocument
  | OverlayCreationDocument
  | MotionClipCreationDocument
  | TransitionCreationDocument
  | AudioCreationDocument;

// Creation types produced by a video generation provider.
export type VideoCreationDocument =
  | R2VCreationDocument
  | T2VCreationDocument
  | I2VCreationDocument
  | S2VCreationDocument;

export interface ElementOutputDocument extends ProjectJsonRecord {
  slot_id: string;
}

export interface SourceAssetRenderSourceDocument extends ProjectJsonRecord {
  type: "source_asset_version";
  version_id: string;
  source_in_tick: number;
  source_out_tick: number | null;
  playback_rate: number;
  loop: boolean;
}

export interface ArtifactRenderSourceDocument extends ProjectJsonRecord {
  type: "artifact_version";
  version_id: string;
  source_in_tick: number;
  source_out_tick: number | null;
  playback_rate: number;
  loop: boolean;
}

export interface ElementOutputRenderSourceDocument extends ProjectJsonRecord {
  type: "element_output";
  element_id: string;
  output_name: string;
  source_in_tick: number;
  source_out_tick: number | null;
  playback_rate: number;
  loop: boolean;
}

export type ElementRenderSourceDocument =
  | SourceAssetRenderSourceDocument
  | ArtifactRenderSourceDocument
  | ElementOutputRenderSourceDocument;

export interface TimelineElementDocument extends ProjectJsonRecord {
  element_id: string;
  label: string;
  enabled: boolean;
  span: TimelineSpanDocument;
  location: ElementLocationDocument | null;
  z_index: number;
  creation: ElementCreationDocument;
  outputs: Record<string, ElementOutputDocument>;
  render_source: ElementRenderSourceDocument | null;
  provenance_refs: string[];
}

export interface TimelineDocument extends ProjectJsonRecord {
  timeline_id: string;
  ticks_per_second: number;
  elements_by_id: Record<string, TimelineElementDocument>;
}

export interface ProjectDocument extends ProjectJsonRecord {
  schema_version: 4;
  project_id: string;
  generation: number;
  created_at: string;
  updated_at: string;
  name: string;
  description: string;
  scenario: "short_drama" | "video_edit" | "general";
  settings: ProjectSettingsDocument;
  strategy: CreativeStrategyDocument;
  sources: ProjectSourceCatalogDocument;
  visual: VisualDevelopmentDocument;
  timelines: ProjectEntityCollection<TimelineDocument>;
  assets: ProjectAssetIndexDocument;
}

export type ProjectServerSyncStatus = "healthy" | "degraded" | "invalid";

export interface ProjectSnapshotEnvelope {
  projectId: string;
  generation: number;
  etag: string;
  syncStatus: ProjectServerSyncStatus;
  project: ProjectDocument;
}

export interface ProjectInvalidSnapshotResponse {
  code: "PROJECT_INVALID";
  syncStatus: "invalid";
  lastGoodGeneration: number | null;
  message: string;
}

export type ProjectSnapshotPollResult =
  | ({ kind: "updated" } & ProjectSnapshotEnvelope)
  | {
      kind: "not_modified";
      etag: string | null;
      generation: number | null;
      syncStatus: ProjectServerSyncStatus;
    }
  | ({ kind: "invalid" } & ProjectInvalidSnapshotResponse);

export type ProjectPatchOperation = {
  op: "add" | "replace" | "remove";
  path: string;
  value?: unknown;
  expectedValueHash: string;
};

export interface ProjectPatchRequest {
  clientCommandId: string;
  editSessionId: string;
  baseGeneration: number;
  baseEtag: string;
  blockToken?: string;
  operations: ProjectPatchOperation[];
}

export interface ProjectPatchResponse {
  projectId: string;
  generation: number;
  etag: string;
  changedPointers: string[];
  project: ProjectDocument;
  editImpact?: {
    affectedElementIds: string[];
    affectedTimelineIds: string[];
    invalidatedArtifactVersionIds: string[];
    renderTimelineIds: string[];
    regenerationRequired: boolean;
    renderBlockedByGeneration: boolean;
  };
}

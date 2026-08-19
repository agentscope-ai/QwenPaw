export type CreatorScenario = "short_drama" | "video_edit" | "general";

export interface ProjectCreateRequest {
  clientRequestId: string;
  name: string;
  description?: string;
  scenario: CreatorScenario;
  aspectRatio: string;
  resolution: string;
  contentType?: string | null;
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

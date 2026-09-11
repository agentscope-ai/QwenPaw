export type PostIngestAction = "NONE" | "ATTACH_SOURCE";

/** Document facts produced by the backend document reader. */
export interface DocumentMetadata {
  format: string;
  pageCount: number;
}

export interface AssetIngestAccepted {
  assetId: string;
  taskId: string;
  status:
    | "QUEUED"
    | "RUNNING"
    | "SUCCEEDED"
    | "FAILED"
    | "CANCELLED"
    | "QUARANTINED";
  progress?: number | null;
  assetVersionId?: string | null;
  result?: Record<string, unknown> | null;
  error?: Record<string, unknown> | null;
}

export interface AssetImportAccepted {
  importId: string;
  taskId: string;
  eventSeq: number;
}

export interface AssetImportItem {
  name: string;
  assetVersionId: string;
  checksum: string;
}

export interface AssetImportFailure {
  name: string;
  error: string;
}

export interface AssetImportView {
  importId: string;
  taskId: string;
  status: string;
  progress?: number | null;
  items: AssetImportItem[];
  failures: AssetImportFailure[];
  error?: Record<string, unknown> | null;
}

/**
 * Pointer to the built long-source graph memory. Present on the asset
 * understanding payload only after the background source_memory_build
 * task succeeded for the current sourceChecksum.
 */
export interface SourceMemoryRef {
  graphPath: string;
  embeddingsPath: string;
  builtAt: string;
  macroCount: number;
}

/** GET /assets/{assetId}/understanding response (fields the UI reads). */
export interface AssetUnderstandingView {
  id: string;
  assetId: string;
  assetVersionId: string;
  sourceChecksum: string;
  summary: string;
  memoryRef?: SourceMemoryRef | null;
  [key: string]: unknown;
}

/** Local cache state of one URL-backed source version (original footage). */
export type SourceCacheState = "cached" | "downloading" | "failed" | "idle";

export interface SourceCacheVersionView {
  assetVersionId: string;
  name: string;
  sourceUrl: string;
  cached: boolean;
  state: SourceCacheState;
  expectedSizeBytes?: number | null;
  receivedBytes?: number;
  error?: string | null;
}

export interface SourceCacheResponse {
  projectId: string;
  versions: SourceCacheVersionView[];
}

export interface SourceCacheDownloadAccepted {
  assetVersionId: string;
  state: SourceCacheState;
  receivedBytes?: number;
  totalBytes?: number | null;
}

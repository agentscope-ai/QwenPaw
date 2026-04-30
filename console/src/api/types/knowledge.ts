export interface KnowledgeBaseSummary {
  id: string;
  index: number;
  name: string;
  slug: string;
  enabled: boolean;
  status: "enabled" | "disabled";
  document_count: number;
  enabled_document_count: number;
  processing_document_count: number;
  created_at: string;
  updated_at: string;
}

export type KnowledgeDocumentStatus = "processing" | "enabled" | "disabled" | "failed";

export interface KnowledgeChunkConfig {
  mode?: "general" | "parent_child";
  granularity: "balanced" | "paragraph" | "sentence";
  separator?: string;
  normalize_whitespace?: boolean;
  llm_grouping?: boolean;
  chunk_size: number;
  chunk_overlap: number;
  parent_separator?: string;
  parent_normalize_whitespace?: boolean;
  parent_chunk_size?: number;
  parent_chunk_overlap?: number;
  child_separator?: string;
  child_normalize_whitespace?: boolean;
  child_chunk_size?: number;
  child_chunk_overlap?: number;
}

export interface KnowledgeUploadFormValues extends KnowledgeChunkConfig {
  retrieval_config: KnowledgeRetrievalConfig;
}

export type KnowledgeIndexingTechnique = "high_quality" | "economy";

export type KnowledgeSearchMethod = "semantic" | "full_text" | "hybrid" | "keyword";

export interface KnowledgeRetrievalConfig {
  indexing_technique: KnowledgeIndexingTechnique;
  search_method: KnowledgeSearchMethod;
  top_k: number;
  score_threshold_enabled: boolean;
  score_threshold: number;
  reranking_enable: boolean;
  weights: {
    vector_weight: number;
    keyword_weight: number;
  };
}

export interface KnowledgeDocumentSummary {
  id: string;
  index: number;
  name: string;
  char_count: number;
  uploaded_at: string;
  updated_at: string;
  status: KnowledgeDocumentStatus;
  enabled: boolean;
  chunk_count: number;
  enabled_chunk_count: number;
  source_filename: string;
  chunk_config: KnowledgeChunkConfig;
  asset_count?: number;
  retrieval_config?: KnowledgeRetrievalConfig;
  error_message?: string;
}

export interface KnowledgeChunkAsset {
  id: string;
  name: string;
  kind: "image" | "video" | "file";
  mime_type: string;
  path: string;
  url: string;
}

export interface KnowledgeChunk {
  id: string;
  index: number;
  name: string;
  content: string;
  char_count: number;
  enabled: boolean;
  status: "enabled" | "disabled";
  created_at: string;
  updated_at: string;
  assets?: KnowledgeChunkAsset[];
}

export interface PaginatedKnowledgeChunks {
  items: KnowledgeChunk[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface KnowledgeUploadCapabilities {
  supported_extensions: string[];
  default_chunk_config: KnowledgeChunkConfig;
  retrieval_config: KnowledgeRetrievalConfig;
  vector_model: {
    available: boolean;
    provider: string;
    base_url: string;
    model_name: string;
    dimensions?: number | null;
    normalized?: boolean | null;
    distance_metric?: string | null;
  };
  requires_embedding: boolean;
  can_upload: boolean;
}

export interface KnowledgeReferenceItem {
  id: string;
  priority: number;
  trigger: "always" | "keyword";
  retrieval_top_k: number;
  usage_rule: string;
  keywords: string[];
}

export interface KnowledgeConfigResponse {
  items: KnowledgeReferenceItem[];
  soul_path: string;
}

export interface KnowledgeVectorConfig {
  embedding_model_config: {
    backend: string;
    api_key: string;
    api_key_configured?: boolean;
    base_url: string;
    model_name: string;
    dimensions: number;
    enable_cache: boolean;
    use_dimensions: boolean;
    max_cache_size: number;
    max_input_length: number;
    max_batch_size: number;
  };
  default_chunk_config: KnowledgeChunkConfig;
  retrieval_config: KnowledgeRetrievalConfig;
}
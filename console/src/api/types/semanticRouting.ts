export interface SemanticRoutingEmbeddingConfig {
  base_url: string;
  api_key: string;
  model_name: string;
  dimensions: number;
  max_batch_size: number;
}

export interface SemanticRoutingConfig {
  enabled: boolean;
  encoder: string;
  top_k: number;
  min_score: number;
  embedding_model_config: SemanticRoutingEmbeddingConfig;
}

export interface KnowledgeBaseMeta {
  id: string;
  name: string;
  domain: string;
  version: number;
  created_at: string;
  updated_at: string;
  description: string;
}

export interface KnowledgeBaseListResponse {
  knowledge_bases: KnowledgeBaseMeta[];
}

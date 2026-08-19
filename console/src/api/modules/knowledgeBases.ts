import { request } from "../request";
import type { KnowledgeBaseListResponse } from "../types/knowledgeBases";

export const knowledgeBasesApi = {
  listKnowledgeBases: () =>
    request<KnowledgeBaseListResponse>("/knowledge-bases"),
};

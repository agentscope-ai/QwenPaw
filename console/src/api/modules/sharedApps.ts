import { request } from "../request";

export interface SharedAppRecord {
  id: string;
  agent_id: string;
  owner_user_id: string;
  status: "draft" | "active" | "retired";
  current_publication_id: string | null;
}

export interface SharedAppPublication {
  id: string;
  shared_app_id: string;
  version: string;
  review_status: "pending" | "approved" | "rejected";
  review_note?: string | null;
  immutable_manifest: {
    display?: { name?: string; description?: string };
    model?: { provider_id?: string; model?: string };
  };
  app_status?: "draft" | "active" | "retired";
  current_publication_id?: string | null;
}

export interface StartSharedAppConversation {
  agent_id: string;
  conversation_id: string;
  publication_id: string;
  version: string;
  locked_model: { provider_id: string; model: string };
}

export const sharedAppsApi = {
  catalog: () => request<{ items: SharedAppPublication[] }>("/shared-app-catalog"),
  mine: () => request<{ items: SharedAppRecord[] }>("/shared-apps/mine"),
  create: (agentId: string) =>
    request<SharedAppRecord>("/shared-apps", {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId }),
    }),
  saveDraft: (appId: string, manifest: Record<string, unknown>) =>
    request<{ revision: number }>(`/shared-apps/${encodeURIComponent(appId)}/drafts`, {
      method: "POST",
      body: JSON.stringify({ manifest }),
    }),
  submit: (appId: string, draftRevision: number) =>
    request<SharedAppPublication>(`/shared-apps/${encodeURIComponent(appId)}/submissions`, {
      method: "POST",
      body: JSON.stringify({ draft_revision: draftRevision }),
    }),
  publications: (appId: string) =>
    request<{ items: SharedAppPublication[] }>(`/shared-apps/${encodeURIComponent(appId)}/publications`),
  start: (appId: string) =>
    request<StartSharedAppConversation>(`/shared-app-catalog/${encodeURIComponent(appId)}/conversations`, { method: "POST" }),
  pending: () => request<{ items: SharedAppPublication[] }>("/admin/shared-app-publications"),
  review: (publicationId: string, decision: "approved" | "rejected", reviewNote: string) =>
    request<SharedAppPublication>(`/admin/shared-app-publications/${encodeURIComponent(publicationId)}/review`, {
      method: "POST",
      body: JSON.stringify({ decision, review_note: reviewNote }),
    }),
  publish: (publication: SharedAppPublication, expectedCurrentId: string | null) =>
    request<SharedAppRecord>(`/admin/shared-app-publications/${encodeURIComponent(publication.id)}/publish`, {
      method: "POST",
      body: JSON.stringify({ publication_id: publication.id, expected_current_id: expectedCurrentId }),
    }),
  retire: (appId: string, expectedCurrentId: string) =>
    request<SharedAppRecord>(`/admin/shared-apps/${encodeURIComponent(appId)}/retire`, {
      method: "POST",
      body: JSON.stringify({ expected_current_id: expectedCurrentId }),
    }),
  rollback: (appId: string, publicationId: string, expectedCurrentId: string | null) =>
    request<SharedAppRecord>(`/admin/shared-apps/${encodeURIComponent(appId)}/rollback`, {
      method: "POST",
      body: JSON.stringify({ publication_id: publicationId, expected_current_id: expectedCurrentId }),
    }),
};

export interface SkillCatalogItem {
  id: string;
  name: string;
  version_id: string;
  version: string;
  content_hash: string;
}
export interface SkillSourceState {
  name: string;
  source_pool_version_id: string | null;
  source_pool_version: string | null;
  detached: boolean;
  update_available: boolean;
  content_hash: string;
}
export interface GovernedSkill extends SkillCatalogItem {
  status: "active" | "disabled";
}
export interface SkillPreview {
  name: string;
  content_hash: string;
}
export interface SkillGrant {
  agent_id: string | null;
  agent_database_id: string;
  enabled: boolean;
  changed_by: string | null;
  updated_at: string | null;
}
export interface SkillPublicationRequest {
  id: string;
  skill_name: string;
  submitted_by: string | null;
  applicant_name?: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  status: "pending" | "approved" | "rejected";
  content_hash: string | null;
  review_version: number;
  published_version_id: string | null;
  reviewed_by: string | null;
  review_note: string | null;
  created_at: string | null;
  reviewed_at: string | null;
}
export interface SkillRequestDetail {
  id: string;
  skill_name: string;
  status: SkillPublicationRequest["status"];
  review_version: number;
  content_hash: string | null;
  files: string[];
}
export interface SkillTargetResult {
  agent_id: string;
  status: "updated" | "unchanged" | "ready" | "skipped" | "failed";
  reason: string;
  name?: string;
  source_pool_version_id?: string;
  expected_content_hash?: string | null;
  expected_version_id?: string;
}

export interface SkillBroadcastConfirmation {
  expected_content_hash: string | null;
  expected_version_id: string;
}

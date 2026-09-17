export interface VideoTemplateSummary {
  templateId: string;
  name: string;
  description: string;
  contentType: string;
  scenario: string;
  colorGrade: string;
  defaultTransitionKind: string;
  previewDescription: string;
  iconEmoji: string;
  captionBlueprints: string[];
  energy: "low" | "mid" | "high";
  density: "low" | "mid" | "high";
  decoration: "low" | "mid" | "high";
  source: "builtin" | "user";
}

export interface VideoTemplateListResponse {
  items: VideoTemplateSummary[];
}

export interface SaveAsTemplateRequest {
  projectId: string;
  name: string;
  description?: string;
  iconEmoji?: string;
  timelineId?: string;
}

export interface SaveAsTemplateResponse {
  templateId: string;
  name: string;
  source: "user";
}

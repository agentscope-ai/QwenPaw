export type SpecialistRole =
  | "source_intelligence_agent"
  | "visual_development_agent"
  | "r2v_generation_director"
  | "ai_editing_director";

export interface CreatorApiError {
  code: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
}

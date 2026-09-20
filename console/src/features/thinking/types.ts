export type ThinkingLevel =
  | "inherit"
  | "off"
  | "minimal"
  | "low"
  | "medium"
  | "high"
  | "xhigh"
  | "max"
  | "budget";
export interface ThinkingPreference {
  level: ThinkingLevel;
  budget_tokens?: number | null;
}
export interface ThinkingControlSpec {
  kind: "unknown" | "unsupported" | "effort" | "budget";
  wire?:
    | "native"
    | "anthropic_budget"
    | "gemini_budget"
    | "anthropic_adaptive"
    | "gemini_level"
    | "compat_budget"
    | "compat_effort";
  efforts: ThinkingLevel[];
  supports_off: boolean;
  budget_min?: number | null;
  budget_max?: number | null;
  budget_default?: number | null;
}
export interface ThinkingView {
  model_source?: "session" | "agent" | "global";
  provider_id?: string | null;
  model_key?: string;
  effective_max_input_length?: number | null;
  model: string | null;
  control: ThinkingControlSpec;
  value: ThinkingPreference;
  effective: ThinkingPreference;
  source: "session" | "agent" | "model";
  reason: string | null;
}

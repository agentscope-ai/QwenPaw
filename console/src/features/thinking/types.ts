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
  kind: "unsupported" | "effort" | "budget";
  efforts: ThinkingLevel[];
  supports_off: boolean;
  budget_min?: number | null;
  budget_max?: number | null;
  budget_default?: number | null;
}
export interface ThinkingView {
  model: string | null;
  control: ThinkingControlSpec;
  value: ThinkingPreference;
  effective: ThinkingPreference;
  source: "session" | "agent" | "model";
  reason: string | null;
}

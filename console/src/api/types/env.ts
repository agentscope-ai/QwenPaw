export interface EnvVar {
  key: string;
  value: string;
}

export interface EnvSpec {
  key: string;
  default: string;
  effective_value: string;
  source: "default" | "system" | "user";
  description_key: string;
  editable: boolean;
  value_type: "string" | "float" | "integer" | "boolean";
  readonly_reason_code: "startup" | "initial_default" | null;
  mutability: "hot_runtime" | "startup_only";
  configured: boolean;
}

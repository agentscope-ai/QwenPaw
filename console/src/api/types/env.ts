export interface EnvVar {
  key: string;
  value: string;
}

export interface EnvSpec {
  key: string;
  default: string;
  effective_value: string;
  source: "default" | "system" | "user";
  description: string;
  description_key: string;
  editable: boolean;
  sensitive: boolean;
  value_type: string;
  choices: string[];
  readonly_reason: string | null;
  readonly_reason_code: "startup" | "initial_default" | null;
  mutability: "hot_runtime" | "hot_process" | "startup_only" | "internal";
  configured: boolean;
}

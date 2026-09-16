export interface EnvVar {
  key: string;
  configured: boolean;
}

export type EnvOperation =
  | { key: string; action: "keep" }
  | { key: string; action: "replace"; value: string }
  | { key: string; action: "delete" };

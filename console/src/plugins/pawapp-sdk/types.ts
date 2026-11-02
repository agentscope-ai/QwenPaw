/** Host SDK extensions to the shared, independently installable PawApp types. */
export * from "../../../../src/qwenpaw/plugins/frontend/paw";
import type { PawSdk as SharedPawSdk } from "../../../../src/qwenpaw/plugins/frontend/paw";
import type {
  PawTasksNamespace,
  PawArtifactsNamespace,
  PawSetupNamespace,
} from "./durable";

export interface PawProjectRef {
  schema_version: 1;
  app_id: string;
  project_id: string;
  kind: string;
  revision: number;
}

export interface PawArtifactPresentation {
  schema_version: 1;
  role: "primary" | "supporting" | "diagnostic" | "source";
  kind: string;
  visibility: "chat" | "app_only";
  preview: "inline" | "link" | "none";
  rank: number;
}

export interface PawArtifactRef {
  schema_version: 1;
  artifact_id: string;
  type: string;
  version: number;
  name: string;
  media_type: string;
  size_bytes: number;
  digest: string;
  producer: Record<string, string>;
  presentation?: PawArtifactPresentation | null;
  created_at: number;
}

export interface PawTaskContext {
  schema_version: 1;
  context_id: string;
  revision: number;
  task_id: string;
  goal: string;
  scope: {
    workspace_id: string;
    source_app_id: string;
    action_id: string;
    engagement: "delegated" | "direct";
  };
  artifact_refs: PawArtifactRef[];
  decision_refs: PawArtifactRef[];
  project_ref: PawProjectRef;
  resume_ref: string;
  approval_request?: import("./contracts").ApprovalRequest | null;
  /** Opaque view declared by the App's registered task experience. */
  view_id?: string | null;
}

export interface PawHandoffRequest {
  schema_version: 1;
  handoff_id: string;
  source_app_id: string;
  target_app_id: string;
  context: PawTaskContext;
  created_at: number;
}

export interface PawAppsNamespace {
  resolveHandoff(
    handoffId: string,
    options?: { workspaceId?: string },
  ): Promise<PawHandoffRequest>;
}

export interface PawSdk extends SharedPawSdk {
  apps: PawAppsNamespace;
  tasks: PawTasksNamespace;
  artifacts: PawArtifactsNamespace;
  setup: PawSetupNamespace;
}

export interface PawSdkFactory {
  forApp(appId: string): PawSdk;
}

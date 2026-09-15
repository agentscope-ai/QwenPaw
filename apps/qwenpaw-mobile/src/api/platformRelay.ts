import { platformRequest } from "./platform";

export interface PlatformRelayQuota {
  used: number;
  limit: number | null;
  can_bind: boolean;
  lifetime_score: number;
  next_tier_score: number | null;
  base_limit?: number;
  extra_limit?: number;
  extra_limit_expires_at?: string | null;
}

export interface PlatformRelayNode {
  id: string;
  qwenpaw_id: string;
  name: string;
  status: string;
  protocol_version: number;
  last_seen_at: string | null;
  created_at: string;
}

export async function getPlatformRelayQuota(): Promise<PlatformRelayQuota> {
  return platformRequest<PlatformRelayQuota>("/api/v1/qwenpaw-relay/quota");
}

export async function listPlatformRelayNodes(): Promise<PlatformRelayNode[]> {
  return platformRequest<PlatformRelayNode[]>("/api/v1/qwenpaw-relay/nodes");
}

export async function revokePlatformRelayNode(nodeId: string): Promise<void> {
  await platformRequest<void>(
    `/api/v1/qwenpaw-relay/nodes/${encodeURIComponent(nodeId)}`,
    { method: "DELETE" },
  );
}

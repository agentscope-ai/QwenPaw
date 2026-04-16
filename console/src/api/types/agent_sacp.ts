// Agent SACP types - mirrors Python AgentSACPConfig, CreateAgentSACPRequest, UpdateAgentSACPRequest, etc.

export type HealthStatus = "healthy" | "unhealthy" | "unknown";

export interface AgentSACPConfig {
  id: string;
  name: string;
  description: string;
  url: string;
  auth_key: string;
  is_internal: boolean;
  internal_agent_id: string | null;
  health_status: HealthStatus;
  last_health_check: string | null; // ISO datetime string
  last_health_error: string | null;
  consecutive_failures: number;
  health_check_enabled: boolean;
  health_check_interval: number; // seconds
  created_at: string; // ISO datetime string
  updated_at: string; // ISO datetime string
}

export interface CreateAgentSACPRequest {
  name: string;
  description?: string;
  url: string;
  auth_key: string;
  is_internal?: boolean;
  internal_agent_id?: string | null;
  health_check_enabled?: boolean;
  health_check_interval?: number; // seconds, 60-3600
}

export interface UpdateAgentSACPRequest {
  name?: string | null;
  description?: string | null;
  url?: string | null;
  auth_key?: string | null;
  is_internal?: boolean | null;
  internal_agent_id?: string | null;
  health_check_enabled?: boolean | null;
  health_check_interval?: number | null; // seconds, 60-3600
}

export interface AgentSACPHealthCheckResult {
  agent_id: string;
  status: HealthStatus;
  checked_at: string; // ISO datetime string
  error: string | null;
}

export interface AgentSACPStorage {
  version: string;
  global_internal_auth_key?: string | null;
  agents: AgentSACPConfig[];
}

import type {
  HubDockerImageCatalog,
  HubHealth,
  HubOverview,
  HubPage,
  HubRuntime,
  HubSettings,
  HubUser,
} from "../api/modules/hub";

export function page<T>(items: T[] = []): HubPage<T> {
  return {
    items,
    page: 1,
    page_size: 20,
    total: items.length,
    pages: 1,
  };
}

export function runtime(overrides: Partial<HubRuntime> = {}): HubRuntime {
  return {
    runtime_id: "personal-user-a",
    tenant_id: "personal-user-a",
    owner_user_id: "user-a",
    owner_username: "owner",
    provisioner: "local",
    host: "127.0.0.1",
    port: 32001,
    state: "running",
    desired_state: "running",
    start_policy: "owner_allowed",
    endpoint: "http://127.0.0.1:32001",
    security_level: "isolated-local",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function hubUser(overrides: Partial<HubUser> = {}): HubUser {
  return {
    user_id: "user-a",
    username: "owner",
    role: "admin",
    disabled: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function hubHealth(overrides: Partial<HubHealth> = {}): HubHealth {
  return {
    status: "ok",
    mode: "hub",
    default_provisioner: "local",
    runtime_available: true,
    runtime_state: "running",
    runtime_desired_state: "running",
    runtime_start_policy: "owner_allowed",
    provisioner_statuses: {
      local: { available: true, security_level: "isolated-local" },
    },
    ...overrides,
  };
}

export function hubOverview(overrides: Partial<HubOverview> = {}): HubOverview {
  return {
    runtime_counts: {
      created: 0,
      starting: 0,
      running: 2,
      stopped: 0,
      failed: 0,
    },
    total_runtimes: 2,
    total_users: 1,
    runtime_available: true,
    host: { cpu_percent: 12, memory_percent: 34, disk_percent: 56 },
    recent_events: [],
    ...overrides,
  };
}

export function hubSettings(overrides: Partial<HubSettings> = {}): HubSettings {
  return {
    config: {
      version: 1,
      control_plane: {
        public_base_url: "https://hub.example.com",
        registration: { enabled: false, default_role: "user" },
        security: {
          ip_blacklist: [],
          trusted_proxy_ips: [],
          login_rate_limit: {
            enabled: true,
            max_attempts: 10,
            window_seconds: 300,
            block_seconds: 900,
          },
          registration_rate_limit: {
            enabled: true,
            max_attempts: 5,
            window_seconds: 3600,
            block_seconds: 3600,
          },
        },
        proxy: {
          max_request_size_mb: 1024,
          request_idle_timeout_seconds: 60,
          response_header_timeout_seconds: 300,
          connect_timeout_seconds: 10,
          websocket_max_message_size_mb: 16,
        },
      },
      runtime: {
        provisioner: "local",
        docker: {
          source: "docker_hub",
          image: "docker.io/agentscope/qwenpaw:latest",
          pull_policy: "if_not_present",
          cpu_limit: 2,
          memory_limit_mb: 4096,
          pids_limit: 1024,
          shm_size_mb: 512,
        },
      },
      capacity: { max_running_runtimes: null },
    },
    revision: 3,
    updated_at: "2026-01-01T00:00:00Z",
    available_provisioners: ["local", "docker"],
    ...overrides,
  };
}

export function dockerCatalog(
  overrides: Partial<HubDockerImageCatalog> = {},
): HubDockerImageCatalog {
  return {
    available: true,
    sources: {
      docker_hub: "docker.io/agentscope/qwenpaw",
      aliyun_acr:
        "agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/qwenpaw",
    },
    official_images: [
      {
        source: "docker_hub",
        reference: "docker.io/agentscope/qwenpaw:latest",
        tag: "latest",
        downloaded: true,
      },
    ],
    local_images: [],
    policy: {
      source: "docker_hub",
      image: "docker.io/agentscope/qwenpaw:latest",
      pull_policy: "if_not_present",
      cpu_limit: 2,
      memory_limit_mb: 4096,
      pids_limit: 1024,
      shm_size_mb: 512,
    },
    ...overrides,
  };
}

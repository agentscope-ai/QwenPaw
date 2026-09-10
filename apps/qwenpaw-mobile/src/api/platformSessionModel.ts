export type PlatformRefreshMode = "web" | "cli";

export interface PlatformRefreshRequest {
  path: string;
  body: Record<string, string>;
}

export function platformRefreshRequest(
  mode: PlatformRefreshMode,
  refreshToken: string,
): PlatformRefreshRequest {
  if (mode === "cli") {
    return {
      path: "/api/cli/v1/auth/refresh",
      body: { refresh_token: refreshToken },
    };
  }
  return {
    path: "/api/v1/auth/refresh",
    body: { refreshToken },
  };
}

export function platformRefreshModes(
  mode?: PlatformRefreshMode,
): PlatformRefreshMode[] {
  return mode ? [mode] : ["web", "cli"];
}

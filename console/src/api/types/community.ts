/** Installer-managed platform identity; never inferred from a display name. */
export interface InstallationOrigin {
  provider: "agentscope-platform";
  resource_id: string;
  resource_type: "plugin" | "app" | "skill";
  installed_version?: string;
  source_url?: string;
}

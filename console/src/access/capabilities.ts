export const Capability = {
  PlatformUse: "platform.use",
  UsersManage: "users.manage",
  PlatformSettingsManage: "platform.settings.manage",
  PublicationsReview: "publications.review",
} as const;

export type Capability = (typeof Capability)[keyof typeof Capability];

export type PlatformRole = "admin" | "member";
export type PlatformMode = "legacy" | "multi_user";

export function can(
  mode: PlatformMode,
  role: PlatformRole | null,
  capability: Capability | string,
): boolean {
  if (mode === "legacy") return true;
  if (capability === Capability.PlatformUse) {
    return role === "admin" || role === "member";
  }
  if (
    capability === Capability.UsersManage ||
    capability === Capability.PlatformSettingsManage ||
    capability === Capability.PublicationsReview
  ) {
    return role === "admin";
  }
  return false;
}

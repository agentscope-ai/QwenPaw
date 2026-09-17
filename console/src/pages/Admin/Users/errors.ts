import type { TFunction } from "i18next";

const GOVERNANCE_ERRORS = {
  last_active_admin: "adminUsers.errors.lastActiveAdmin",
  username_already_exists: "adminUsers.errors.usernameExists",
  user_not_found: "adminUsers.errors.userNotFound",
} as const;

export function formatGovernanceError(error: unknown, t: TFunction): string {
  const message = error instanceof Error ? error.message : String(error);
  const code = Object.keys(GOVERNANCE_ERRORS).find((candidate) =>
    message.includes(candidate),
  ) as keyof typeof GOVERNANCE_ERRORS | undefined;

  if (!code) {
    return message || t("adminUsers.errors.unknown", "Operation failed");
  }
  return t(GOVERNANCE_ERRORS[code]);
}

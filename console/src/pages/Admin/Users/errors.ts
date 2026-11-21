import type { TFunction } from "i18next";
import { parseErrorDetail } from "../../../utils/error";
import { interactionErrorText } from "../../../utils/interactionText";

const GOVERNANCE_ERRORS = {
  last_active_admin: "adminUsers.errors.lastActiveAdmin",
  username_already_exists: "adminUsers.errors.usernameExists",
  user_not_found: "adminUsers.errors.userNotFound",
  user_disabled: "adminUsers.errors.userDisabled",
} as const;

export function formatGovernanceError(error: unknown, t: TFunction): string {
  const message = error instanceof Error ? error.message : String(error);
  const detail = parseErrorDetail(error);
  const diagnostic =
    typeof detail === "string" ? detail : String(detail?.code ?? message);
  const code = Object.keys(GOVERNANCE_ERRORS).find((candidate) =>
    diagnostic.includes(candidate),
  ) as keyof typeof GOVERNANCE_ERRORS | undefined;

  if (!code) {
    return interactionErrorText(
      message || t("adminUsers.errors.unknown", "Operation failed"),
    );
  }
  return t(GOVERNANCE_ERRORS[code]);
}

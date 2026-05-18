import { parseErrorDetail } from "@/utils/error";

export type BackupTrustMode = "legacy" | "foreign";

export function trustModeFromError(error: unknown): BackupTrustMode | null {
  return trustModeFromErrorCode(parseErrorDetail(error)?.code);
}

export function trustModeFromErrorCode(code: unknown): BackupTrustMode | null {
  switch (String(code ?? "")) {
    case "backup_legacy_unsigned":
      return "legacy";
    case "backup_signature_mismatch":
    case "backup_unknown_signature_scheme":
      return "foreign";
    default:
      return null;
  }
}

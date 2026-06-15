export interface PersonaWriteApprovalDetails {
  proposal_id: string;
  relative_path: string;
  absolute_path?: string;
  operation: string;
  old_sha256: string;
  new_sha256: string;
  current_content?: string;
  proposed_content?: string;
  content_preview?: string;
  current_truncated?: boolean;
  proposed_truncated?: boolean;
}

export function resolvePersonaWriteProposedContent(
  details: PersonaWriteApprovalDetails,
): string {
  if (typeof details.proposed_content === "string") {
    return details.proposed_content;
  }
  return details.content_preview ?? "";
}

export function resolvePersonaWriteCurrentContent(
  details: PersonaWriteApprovalDetails,
): string {
  return details.current_content ?? "";
}

const PERSONA_FILE_TOOLS = new Set(["write_file", "edit_file", "append_file"]);

export function coercePersonaWriteDetails(
  personaWrite: PersonaWriteApprovalDetails | undefined,
  toolName: string,
  toolParams: Record<string, unknown> | undefined,
): PersonaWriteApprovalDetails | undefined {
  if (
    personaWrite &&
    (personaWrite.proposed_content ||
      personaWrite.content_preview ||
      personaWrite.relative_path)
  ) {
    return personaWrite;
  }

  const params = toolParams ?? {};
  const filePath = params.file_path ?? params.path;
  const proposed =
    params.proposed_content ?? params.content ?? params.new_content;
  const current = params.current_content;

  if (typeof filePath !== "string" || typeof proposed !== "string") {
    return personaWrite;
  }
  if (!PERSONA_FILE_TOOLS.has(toolName)) {
    return personaWrite;
  }

  const operation =
    typeof params.operation === "string"
      ? params.operation
      : toolName === "write_file"
        ? "write"
        : toolName === "edit_file"
          ? "edit"
          : "append";

  return {
    proposal_id: personaWrite?.proposal_id ?? "",
    relative_path: filePath,
    operation,
    old_sha256: String(params.old_sha256 ?? personaWrite?.old_sha256 ?? ""),
    new_sha256: String(params.new_sha256 ?? personaWrite?.new_sha256 ?? ""),
    proposed_content: proposed,
    current_content:
      typeof current === "string" ? current : personaWrite?.current_content,
    current_truncated: personaWrite?.current_truncated,
    proposed_truncated: personaWrite?.proposed_truncated,
    content_preview:
      personaWrite?.content_preview ??
      (proposed.length > 500 ? proposed.slice(0, 500) : proposed),
  };
}

export function isPersonaWriteApproval(
  value: unknown,
): value is PersonaWriteApprovalDetails {
  if (!value || typeof value !== "object") {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.relative_path === "string" &&
    (typeof record.proposed_content === "string" ||
      typeof record.content_preview === "string")
  );
}

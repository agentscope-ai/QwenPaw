export interface FileBaselineWriteApprovalDetails {
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

export function resolveFileBaselineWriteProposedContent(
  details: FileBaselineWriteApprovalDetails,
): string {
  if (typeof details.proposed_content === "string") {
    return details.proposed_content;
  }
  return details.content_preview ?? "";
}

export function resolveFileBaselineWriteCurrentContent(
  details: FileBaselineWriteApprovalDetails,
): string {
  return details.current_content ?? "";
}

const PERSONA_FILE_TOOLS = new Set(["write_file", "edit_file", "append_file"]);

export function coerceFileBaselineWriteDetails(
  fileBaselineWrite: FileBaselineWriteApprovalDetails | undefined,
  toolName: string,
  toolParams: Record<string, unknown> | undefined,
): FileBaselineWriteApprovalDetails | undefined {
  if (
    fileBaselineWrite &&
    (fileBaselineWrite.proposed_content ||
      fileBaselineWrite.content_preview ||
      fileBaselineWrite.relative_path)
  ) {
    return fileBaselineWrite;
  }

  const params = toolParams ?? {};
  const filePath = params.file_path ?? params.path;
  const proposed =
    params.proposed_content ?? params.content ?? params.new_content;
  const current = params.current_content;

  if (typeof filePath !== "string" || typeof proposed !== "string") {
    return fileBaselineWrite;
  }
  if (!PERSONA_FILE_TOOLS.has(toolName)) {
    return fileBaselineWrite;
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
    proposal_id: fileBaselineWrite?.proposal_id ?? "",
    relative_path: filePath,
    operation,
    old_sha256: String(params.old_sha256 ?? fileBaselineWrite?.old_sha256 ?? ""),
    new_sha256: String(params.new_sha256 ?? fileBaselineWrite?.new_sha256 ?? ""),
    proposed_content: proposed,
    current_content:
      typeof current === "string" ? current : fileBaselineWrite?.current_content,
    current_truncated: fileBaselineWrite?.current_truncated,
    proposed_truncated: fileBaselineWrite?.proposed_truncated,
    content_preview:
      fileBaselineWrite?.content_preview ??
      (proposed.length > 500 ? proposed.slice(0, 500) : proposed),
  };
}

export function isFileBaselineWriteApproval(
  value: unknown,
): value is FileBaselineWriteApprovalDetails {
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

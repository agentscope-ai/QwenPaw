import {
  buildFileCenterPath,
  type FileLocator,
} from "../../features/files-workspace/fileLocator";

export function memoryLocatorsFromInboxPayload(
  payload: Record<string, unknown> | undefined,
  agentId: string,
): FileLocator[] {
  const files = payload?.memory_files;
  if (!Array.isArray(files)) return [];
  const locators: FileLocator[] = [];
  for (const item of files) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const record = item as Record<string, unknown>;
    const locator: FileLocator = {
      category: "memory",
      agentId,
      relativePath:
        typeof record.path === "string" ? record.path : "",
      memoryScope:
        record.scope === "private" || record.scope === "public"
          ? record.scope
          : undefined,
      memorySection:
        record.section === "daily" || record.section === "digest"
          ? record.section
          : undefined,
    };
    try {
      buildFileCenterPath(locator);
      locators.push(locator);
    } catch {
      // Ignore malformed or legacy payload entries.
    }
  }
  return locators;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function sourceConversationIdFromInboxPayload(
  payload: Record<string, unknown> | undefined,
): string | null {
  const value = payload?.source_conversation_id;
  return typeof value === "string" && UUID_PATTERN.test(value) ? value : null;
}

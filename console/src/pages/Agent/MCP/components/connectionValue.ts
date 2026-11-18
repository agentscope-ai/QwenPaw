export function readConnection(json: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(json);
    return value && typeof value === "object" && !Array.isArray(value)
      ? value
      : null;
  } catch {
    return null;
  }
}

export function connectionError(
  config: Record<string, unknown> | null,
): string | null {
  if (!config) return "skills.configInvalidJson";
  if (typeof config.name !== "string" || !config.name.trim())
    return "mcp.form.nameRequired";
  const local = config.transport === "stdio";
  const endpoint = local ? config.command : config.url;
  if (typeof endpoint !== "string" || !endpoint.trim())
    return local ? "mcp.form.commandRequired" : "mcp.form.urlRequired";
  return null;
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function projectDirsEqual(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (!Array.isArray(left) || !Array.isArray(right)) return false;
  if (left.length !== right.length) return false;
  return left.every((entry, index) => {
    const other = right[index];
    if (entry === other) return true;
    const a = record(entry);
    const b = record(other);
    return Boolean(a && b && a.path === b.path && a.label === b.label);
  });
}

/** Compare fields consumed by the session UI, not arbitrary plugin payloads. */
export function runtimeContextEqual(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  const a = record(left);
  const b = record(right);
  const aModel = record(a?.model_slot_override);
  const bModel = record(b?.model_slot_override);
  return (
    a?.project_dir === b?.project_dir &&
    projectDirsEqual(a?.project_dirs, b?.project_dirs) &&
    aModel?.provider_id === bModel?.provider_id &&
    aModel?.model === bModel?.model
  );
}

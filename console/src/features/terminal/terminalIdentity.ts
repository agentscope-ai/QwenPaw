const STORAGE_KEY = "qwenpaw-terminal-groups";
let groups: Record<string, string> | undefined;

function readGroups(): Record<string, string> {
  if (!groups) {
    try {
      const stored = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "{}");
      groups =
        stored && typeof stored === "object" && !Array.isArray(stored)
          ? (Object.fromEntries(
              Object.entries(stored).filter(
                ([, value]) =>
                  typeof value === "string" && /^[0-9a-f-]{36}$/i.test(value),
              ),
            ) as Record<string, string>)
          : {};
    } catch {
      groups = {};
    }
  }
  return groups!;
}

function save() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(groups));
  } catch {
    // In-memory identity still survives navigation in restricted browsers.
  }
}

function createTerminalGroupId(): string {
  if (crypto.randomUUID) return crypto.randomUUID();

  // getRandomValues also works on HTTP origins outside localhost.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10).join(""),
  ].join("-");
}

export function terminalGroup(agentId: string, sessionId: string): string {
  const key = JSON.stringify([agentId, sessionId]);
  const entries = readGroups();
  if (!entries[key]) {
    entries[key] = createTerminalGroupId();
    save();
  }
  return entries[key];
}

export function migrateTerminalGroup(
  agentId: string,
  fromId: string,
  toId: string,
): void {
  if (fromId === toId) return;
  const entries = readGroups();
  const from = JSON.stringify([agentId, fromId]);
  const to = JSON.stringify([agentId, toId]);
  if (entries[from]) {
    entries[to] = entries[from];
    delete entries[from];
    save();
  }
}

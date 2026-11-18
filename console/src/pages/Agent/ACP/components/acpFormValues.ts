export function parseArgsText(value: unknown): string[] {
  return String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseEnvText(value: unknown): Record<string, string> {
  return String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((acc, line) => {
      const index = line.indexOf("=");
      if (index >= 0) {
        const key = line.slice(0, index).trim();
        const envValue = line.slice(index + 1).trim();
        if (key) acc[key] = envValue;
      }
      return acc;
    }, {});
}

export function stringifyArgs(args: string[] = []): string {
  return args.join("\n");
}

export function stringifyEnv(env: Record<string, string> = {}): string {
  return Object.entries(env)
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
}

const SILENCED_PATTERNS = [
  ":first-child",
  "pseudo class",
  "potentially unsafe",
];

let installed = false;

function shouldSilence(args: unknown[]): boolean {
  const msg = args[0]?.toString() || "";
  return SILENCED_PATTERNS.some((pattern) => msg.includes(pattern));
}

export function installTauriConsoleNoiseFilter(): void {
  if (installed) return;
  installed = true;

  const originalError = console.error;
  const originalWarn = console.warn;

  console.error = function (...args: unknown[]) {
    if (shouldSilence(args)) return;
    originalError.apply(console, args as []);
  };

  console.warn = function (...args: unknown[]) {
    if (shouldSilence(args)) return;
    originalWarn.apply(console, args as []);
  };
}

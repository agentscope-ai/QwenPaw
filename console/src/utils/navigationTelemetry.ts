export type NavigationEvent = {
  ts: number;
  source: string;
  from?: string;
  to: string;
  reason: string;
  meta?: Record<string, string | number | boolean | undefined>;
};

const TRACE_KEY = "copaw.navigation.trace";
const MAX_TRACE_ITEMS = 200;

function readTrace(): NavigationEvent[] {
  const raw = sessionStorage.getItem(TRACE_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as NavigationEvent[];
  } catch {
    return [];
  }
}

function writeTrace(items: NavigationEvent[]): void {
  sessionStorage.setItem(TRACE_KEY, JSON.stringify(items));
}

export function trackNavigation(event: Omit<NavigationEvent, "ts">): void {
  const record: NavigationEvent = {
    ...event,
    ts: Date.now(),
  };

  const current = readTrace();
  const next = [...current, record].slice(-MAX_TRACE_ITEMS);
  writeTrace(next);

  if (import.meta.env.DEV) {
    // Keep this lightweight for troubleshooting route transitions.
    console.info("[nav]", record);
  }
}

export function getNavigationTrace(): NavigationEvent[] {
  return readTrace();
}

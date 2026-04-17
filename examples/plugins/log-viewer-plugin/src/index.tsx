/**
 * log-viewer-plugin — QwenPaw frontend plugin
 *
 * Registers a page that tails and filters the backend log file.
 * Demonstrates how a plugin calls host APIs (getApiUrl / getApiToken)
 * to make authenticated requests without hard-coding any base URL.
 *
 * Backend API: GET /api/console/debug/backend-logs?lines=200
 *
 * Build:   npm install && npm run build
 * Install: cp -r . ~/.qwenpaw/plugins/log-viewer-plugin
 */

const { React, getApiUrl, getApiToken } = (window as any).QwenPaw.host;
const useState = React.useState as typeof import("react").useState;
const useEffect = React.useEffect as typeof import("react").useEffect;
const useCallback = React.useCallback as typeof import("react").useCallback;
const useMemo = React.useMemo as typeof import("react").useMemo;
const useRef = React.useRef as typeof import("react").useRef;

// ── Types ────────────────────────────────────────────────────────────────────

interface LogResponse {
    path: string;
    exists: boolean;
    lines: number;
    updated_at: number | null;
    size: number;
    content: string;
}

type LevelFilter = "all" | "error" | "warning" | "info" | "debug";

// ── API ──────────────────────────────────────────────────────────────────────

async function fetchLogs(lines: number): Promise<LogResponse> {
    const token: string = typeof getApiToken === "function" ? getApiToken() : "";
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const url = getApiUrl(`/console/debug/backend-logs?lines=${lines}`);
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
    return res.json();
}

// ── Inline styles ────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
    page: { padding: "20px 24px", fontFamily: "'SF Mono','Cascadia Code','Fira Code',Consolas,'Courier New',monospace", fontSize: 13, color: "#cdd6f4", background: "#1e1e2e", minHeight: "100vh", boxSizing: "border-box" },
    header: { display: "flex", alignItems: "center", gap: 16, marginBottom: 16 },
    title: { fontSize: 18, fontWeight: 700, color: "#cdd6f4", fontFamily: "inherit" },
    refreshed: { fontSize: 11, color: "#6c7086", marginLeft: "auto" },
    toolbar: { display: "flex", alignItems: "center", gap: 10, marginBottom: 16, flexWrap: "wrap" },
    label: { fontSize: 12, color: "#89b4fa", whiteSpace: "nowrap" },
    select: { padding: "5px 8px", borderRadius: 6, border: "1px solid #45475a", background: "#313244", color: "#cdd6f4", fontSize: 12, cursor: "pointer", outline: "none" },
    searchInput: { flex: 1, minWidth: 140, maxWidth: 280, padding: "5px 10px", borderRadius: 6, border: "1px solid #45475a", background: "#313244", color: "#cdd6f4", fontSize: 12, outline: "none" },
    btn: { padding: "6px 14px", border: "none", borderRadius: 6, background: "#89b4fa", color: "#1e1e2e", fontSize: 12, cursor: "pointer", fontWeight: 600, whiteSpace: "nowrap" },
    btnDisabled: { padding: "6px 14px", border: "none", borderRadius: 6, background: "#89b4fa", color: "#1e1e2e", fontSize: 12, cursor: "not-allowed", fontWeight: 600, whiteSpace: "nowrap", opacity: 0.6 },
    btnDanger: { padding: "6px 14px", border: "none", borderRadius: 6, background: "#f38ba8", color: "#1e1e2e", fontSize: 12, cursor: "pointer", fontWeight: 600, whiteSpace: "nowrap" },
    errorBanner: { background: "rgba(243,76,92,.12)", border: "1px solid #f3515c", borderRadius: 6, padding: "10px 16px", color: "#f38ba8", marginBottom: 14, display: "flex", alignItems: "center", gap: 10, fontSize: 13 },
    empty: { textAlign: "center", color: "#6c7086", padding: "60px 0", fontSize: 14 },
    apiInfo: { background: "#181825", border: "1px solid #313244", borderRadius: 6, padding: "10px 14px", marginBottom: 16, fontSize: 12, color: "#6c7086", lineHeight: 1.7 },
    apiLabel: { color: "#89b4fa", fontWeight: 600, marginRight: 6 },
    apiValue: { color: "#a6e3a1" },
    metaBar: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 14px", background: "#181825", borderBottom: "1px solid #313244", fontSize: 11 },
    metaPath: { color: "#6c7086" },
    metaCount: { color: "#a6e3a1" },
    logBody: { maxHeight: "calc(100vh - 230px)", overflowY: "auto", background: "#181825" },
    logLine: { display: "flex", gap: 12, padding: "1px 12px", lineHeight: 1.6, borderBottom: "1px solid #1e1e2e", fontSize: 12 },
    lineNum: { minWidth: 36, textAlign: "right", userSelect: "none", opacity: 0.4, flexShrink: 0, color: "#555" },
    logWrap: { borderRadius: 8, border: "1px solid #313244", overflow: "hidden" },
};

// ── Helpers ──────────────────────────────────────────────────────────────────

const LEVEL_OPTIONS: LevelFilter[] = ["all", "error", "warning", "info", "debug"];
const LINE_OPTIONS = [50, 200, 500, 1000, 5000];

function levelColor(line: string): string {
    if (/\bERROR\b/.test(line)) return "#ff4d4f";
    if (/\bWARNING\b|\bWARN\b/.test(line)) return "#fa8c16";
    if (/\bINFO\b/.test(line)) return "#52c41a";
    if (/\bDEBUG\b/.test(line)) return "#8c8c8c";
    return "#d4d4d4";
}

function levelBg(line: string): string {
    if (/\bERROR\b/.test(line)) return "rgba(255,77,79,.07)";
    if (/\bWARNING\b|\bWARN\b/.test(line)) return "rgba(250,140,22,.05)";
    return "transparent";
}

function HighlightedLine({ line, needle }: { line: string; needle: string }) {
    if (!needle) return <span>{line}</span>;
    const idx = line.toLowerCase().indexOf(needle.toLowerCase());
    if (idx === -1) return <span>{line}</span>;
    return (
        <span>
            {line.slice(0, idx)}
            <mark style={{ background: "#ffe58f", color: "#000", borderRadius: 2 }}>
                {line.slice(idx, idx + needle.length)}
            </mark>
            {line.slice(idx + needle.length)}
        </span>
    );
}

// ── LogViewerPage ─────────────────────────────────────────────────────────────

function LogViewerPage() {
    const [lineCount, setLineCount] = useState(200);
    const [level, setLevel] = useState<LevelFilter>("all");
    const [search, setSearch] = useState("");
    const [newestFirst, setNewestFirst] = useState(true);
    const [autoRefresh, setAutoRefresh] = useState(true);
    const [data, setData] = useState<LogResponse | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [lastRefreshed, setLastRefreshed] = useState("");
    const endRef = useRef<HTMLDivElement | null>(null);

    const resolvedUrl = useMemo(
        () => getApiUrl(`/console/debug/backend-logs?lines=${lineCount}`),
        [lineCount],
    );

    const refresh = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const result = await fetchLogs(lineCount);
            setData(result);
            setLastRefreshed(new Date().toLocaleTimeString());
        } catch (e: any) {
            setError(e?.message ?? "Request failed");
        } finally {
            setLoading(false);
        }
    }, [lineCount]);

    useEffect(() => { refresh(); }, []);

    useEffect(() => {
        if (!autoRefresh) return;
        let cancelled = false;
        const tick = async () => {
            if (cancelled) return;
            await refresh();
            if (!cancelled) setTimeout(tick, 3000);
        };
        const id = setTimeout(tick, 3000);
        return () => { cancelled = true; clearTimeout(id); };
    }, [autoRefresh, refresh]);

    useEffect(() => {
        if (!newestFirst) endRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [data, newestFirst]);

    const lines = useMemo(() => {
        const raw = data?.content ?? "";
        if (!raw.trim()) return [] as string[];
        const all = raw.split("\n").filter(Boolean);
        return newestFirst ? [...all].reverse() : all;
    }, [data, newestFirst]);

    const filtered = useMemo(() => {
        const q = search.trim().toLowerCase();
        return lines.filter((ln: string) => {
            if (level !== "all") {
                const lvl = level.toUpperCase();
                if (!ln.includes(` ${lvl} `) && !ln.includes(`| ${lvl} `) && !ln.includes(`${lvl} `))
                    return false;
            }
            return !q || ln.toLowerCase().includes(q);
        });
    }, [lines, level, search]);

    return (
        <div style={s.page}>
            {/* Header */}
            <div style={s.header}>
                <span style={s.title}>📋 Log Viewer Plugin</span>
                {lastRefreshed && <span style={s.refreshed}>Last refreshed: {lastRefreshed}</span>}
            </div>

            {/* API info */}
            <div style={s.apiInfo}>
                <span style={s.apiLabel}>API endpoint:</span>
                <span style={s.apiValue}>{resolvedUrl}</span>
                <br />
                <span style={s.apiLabel}>Auth:</span>
                <span style={s.apiValue}>{getApiToken() ? "Bearer token ✓" : "No token (anonymous)"}</span>
            </div>

            {/* Toolbar */}
            <div style={s.toolbar}>
                <span style={s.label}>Level</span>
                <select value={level} onChange={(e: any) => setLevel(e.target.value)} style={s.select}>
                    {LEVEL_OPTIONS.map((l) => (
                        <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>
                    ))}
                </select>

                <span style={s.label}>Lines</span>
                <select value={lineCount} onChange={(e: any) => setLineCount(Number(e.target.value))} style={s.select}>
                    {LINE_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>

                <input
                    type="text"
                    placeholder="Search…"
                    value={search}
                    onChange={(e: any) => setSearch(e.target.value)}
                    style={s.searchInput}
                />

                <span style={s.label}>Newest first</span>
                <input type="checkbox" checked={newestFirst} onChange={(e: any) => setNewestFirst(e.target.checked)} style={{ cursor: "pointer" }} />

                <span style={s.label}>Auto-refresh</span>
                <input type="checkbox" checked={autoRefresh} onChange={(e: any) => setAutoRefresh(e.target.checked)} style={{ cursor: "pointer" }} />

                <button onClick={refresh} disabled={loading} style={loading ? s.btnDisabled : s.btn}>
                    {loading ? "Loading…" : "⟳  Refresh"}
                </button>
            </div>

            {/* Error banner */}
            {error && (
                <div style={s.errorBanner}>
                    ⚠ {error}
                    <button onClick={refresh} style={s.btnDanger}>Retry</button>
                </div>
            )}

            {/* Empty / loading */}
            {!data && !loading && !error && <div style={s.empty}>No data yet.</div>}
            {loading && !data && <div style={s.empty}>Loading…</div>}

            {/* Log output */}
            {data && (
                <div style={s.logWrap}>
                    <div style={s.metaBar}>
                        <span style={s.metaPath}>{data.path}</span>
                        <span style={s.metaCount}>{filtered.length} lines</span>
                    </div>
                    <div style={s.logBody}>
                        {!data.exists ? (
                            <div style={s.empty}>Log file not found: {data.path}</div>
                        ) : filtered.length === 0 ? (
                            <div style={s.empty}>No matching log lines.</div>
                        ) : (
                            filtered.map((ln: string, i: number) => (
                                <div
                                    key={i}
                                    style={{ ...s.logLine, background: levelBg(ln), borderLeft: `3px solid ${levelColor(ln)}` }}
                                >
                                    <span style={s.lineNum}>{i + 1}</span>
                                    <span style={{ color: levelColor(ln), flex: 1, wordBreak: "break-all" }}>
                                        <HighlightedLine line={ln} needle={search} />
                                    </span>
                                </div>
                            ))
                        )}
                        <div ref={endRef} />
                    </div>
                </div>
            )}
        </div>
    );
}

// ── Plugin class ──────────────────────────────────────────────────────────────

class LogViewerPlugin {
    readonly id = "log-viewer-plugin";

    setup(): void {
        (window as any).QwenPaw.registerRoutes?.(this.id, [
            {
                path: "/plugin/log-viewer-plugin/logs",
                component: LogViewerPage,
                label: "Log Viewer",
                icon: "📋",
                priority: 20,
            },
        ]);
    }
}

new LogViewerPlugin().setup();
new LogViewerPlugin().setup();

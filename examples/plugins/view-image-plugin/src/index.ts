/**
 * view-image-plugin — QwenPaw frontend plugin
 *
 * Registers a custom renderer for the "view_image" tool.
 * When the agent calls view_image, the image is displayed inline and a
 * collapsible JSON inspector shows the raw message for debugging.
 *
 * ## Plugin contract
 *
 * Access shared dependencies via `window.__QWENPAW__` (React, getApiUrl, …).
 * Register capabilities by implementing `setup()` in the plugin class:
 *   - `window.register_routes(id, routes[])`     — page-level routes
 *   - `window.register_tool_render(id, renderers)` — tool message renderers
 *
 * ## Build & Install
 *
 *   npm install && npm run build
 *   cp -r . ~/.qwenpaw/plugins/view-image-plugin
 */

const { React, getApiUrl, getApiToken } = (window as any).__QWENPAW__;
const { useState, useMemo, useCallback } = React;

// ── Inline styles (no external CSS dependency) ──────────────────────────────

const wrapperStyle: Record<string, unknown> = {
    border: "1px solid #e0e0e0",
    borderRadius: 6,
    overflow: "hidden",
    fontSize: 13,
    fontFamily: "inherit",
    margin: "4px 0",
    background: "#fafafa",
};

const imgStyle: Record<string, unknown> = {
    display: "block",
    maxWidth: "100%",
    maxHeight: 480,
    objectFit: "contain",
    background: "#000",
};

const headerStyle: Record<string, unknown> = {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "6px 10px",
    cursor: "pointer",
    userSelect: "none",
    background: "#f0f0f0",
};

const badgeStyle: Record<string, unknown> = {
    fontWeight: 600,
    whiteSpace: "nowrap",
};

const subtitleStyle: Record<string, unknown> = {
    flex: 1,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    color: "#666",
    fontSize: 12,
};

const toggleStyle: Record<string, unknown> = {
    marginLeft: "auto",
    color: "#999",
    fontSize: 11,
    whiteSpace: "nowrap",
};

const preStyle: Record<string, unknown> = {
    margin: 0,
    padding: "10px 12px",
    overflowX: "auto",
    background: "#1e1e1e",
    color: "#d4d4d4",
    fontSize: 12,
    lineHeight: 1.5,
    whiteSpace: "pre-wrap",
    wordBreak: "break-all",
};

// ── Auth helper ──────────────────────────────────────────────────────────────

/**
 * Build the backend preview URL for a local file path.
 * NOTE: <img> cannot carry Authorization headers, so the token is
 * appended as a query parameter specifically for image preview URLs.
 */
function toPreviewUrl(rawPath: string): string {
    if (!rawPath) return "";
    if (rawPath.startsWith("http://") || rawPath.startsWith("https://"))
        return rawPath;

    let filePath = rawPath.startsWith("file://") ? rawPath.slice(7) : rawPath;
    if (!filePath.startsWith("/")) filePath = "/" + filePath;

    const apiBase: string =
        typeof getApiUrl === "function"
            ? getApiUrl("").replace(/\/api$/, "")
            : "";

    const url = `${apiBase}/api/files/preview/${filePath.replace(/^\/+/, "")}`;

    const token: string =
        typeof getApiToken === "function"
            ? getApiToken()
            : localStorage.getItem("qwenpaw_auth_token") ?? "";

    return token ? `${url}?token=${encodeURIComponent(token)}` : url;
}

// ── Component ────────────────────────────────────────────────────────────────

/**
 * Custom renderer for the "view_image" tool.
 *
 * Props shape expected by the host:
 *   data: IAgentScopeRuntimeMessage  (the full message object)
 *
 * - Parses arguments.image_path from content[0].data.arguments
 * - Renders the image via /api/files/preview
 * - Shows a collapsible raw-JSON inspector for debugging
 */
function ViewImageRender({ data }: { data: any }) {
    const [open, setOpen] = useState(false);

    const json = useMemo(() => JSON.stringify(data, null, 2), [data]);

    const firstData = data?.content?.[0]?.data;
    const toolName: string = firstData?.name ?? "view_image";

    const rawArgs = firstData?.arguments;
    const args: Record<string, any> =
        typeof rawArgs === "string"
            ? (() => { try { return JSON.parse(rawArgs); } catch { return {}; } })()
            : (rawArgs ?? {});

    const imagePath: string = args?.image_path ?? "";
    const imgUrl = toPreviewUrl(imagePath);

    const handleToggle = useCallback(() => setOpen((v: boolean) => !v), []);
    const handleImgError = useCallback((e: any) => {
        if (e.currentTarget) e.currentTarget.style.display = "none";
    }, []);

    return React.createElement(
        "div",
        { style: wrapperStyle },
        imgUrl && React.createElement("img", {
            src: imgUrl, alt: imagePath, style: imgStyle, onError: handleImgError,
        }),
        React.createElement(
            "div",
            { style: headerStyle, onClick: handleToggle },
            React.createElement("span", { style: badgeStyle }, `🖼 ${toolName}`),
            imagePath && React.createElement("span", { style: subtitleStyle }, imagePath),
            React.createElement("span", { style: toggleStyle }, open ? "▲ collapse" : "▼ expand"),
        ),
        open && React.createElement("pre", { style: preStyle }, json),
    );
}

// ── Plugin class ─────────────────────────────────────────────────────────────

class ViewImagePlugin {
    readonly id = "view-image-plugin";

    setup(): void {
        this.registerToolRenderers();
    }

    private registerToolRenderers(): void {
        (window as any).register_tool_render?.(this.id, {
            view_image: ViewImageRender,
        });
    }
}

const plugin = new ViewImagePlugin();
plugin.setup();

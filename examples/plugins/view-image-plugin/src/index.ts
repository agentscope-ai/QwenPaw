/**
 * view-image-plugin — QwenPaw frontend plugin
 *
 * Registers a custom renderer for the "view_image" tool.
 * When the agent calls view_image, the image is displayed inline and a
 * collapsible JSON inspector shows the raw message for debugging.
 *
 * Build:   npm install && npm run build
 * Install: cp -r . ~/.qwenpaw/plugins/view-image-plugin
 */

const { React, getApiUrl, getApiToken } = (window as any).QwenPaw.host;
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

// ── URL helper ───────────────────────────────────────────────────────────────

/**
 * Convert a local file path to a browser-accessible preview URL.
 * Uses host's getApiUrl to build the /api/files/preview/... endpoint and
 * appends the auth token as a query param (<img> cannot send headers).
 */
function toDisplayUrl(rawPath: string): string {
  if (!rawPath) return "";
  if (rawPath.startsWith("http://") || rawPath.startsWith("https://"))
    return rawPath;

  let filePath = rawPath.startsWith("file://") ? rawPath.slice(7) : rawPath;
  if (!filePath.startsWith("/")) filePath = "/" + filePath;

  const url = getApiUrl(`/files/preview/${filePath.replace(/^\/+/, "")}`);
  const token: string = getApiToken();
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
 * - Renders the image via /api/files/preview (token passed as query param)
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
      ? (() => {
          try {
            return JSON.parse(rawArgs);
          } catch {
            return {};
          }
        })()
      : rawArgs ?? {};

  const imagePath: string = args?.image_path ?? "";
  const imgUrl = toDisplayUrl(imagePath);

  const handleToggle = useCallback(() => setOpen((v: boolean) => !v), []);
  const handleImgError = useCallback((e: any) => {
    if (e.currentTarget) e.currentTarget.style.display = "none";
  }, []);

  return React.createElement(
    "div",
    { style: wrapperStyle },
    imgUrl &&
      React.createElement("img", {
        src: imgUrl,
        alt: imagePath,
        style: imgStyle,
        onError: handleImgError,
      }),
    React.createElement(
      "div",
      { style: headerStyle, onClick: handleToggle },
      React.createElement("span", { style: badgeStyle }, `🖼 ${toolName}`),
      imagePath &&
        React.createElement("span", { style: subtitleStyle }, imagePath),
      React.createElement(
        "span",
        { style: toggleStyle },
        open ? "▲ collapse" : "▼ expand",
      ),
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
    (window as any).QwenPaw.registerToolRender?.(this.id, {
      view_image: ViewImageRender,
    });
  }
}

const plugin = new ViewImagePlugin();
plugin.setup();

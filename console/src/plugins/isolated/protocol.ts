/** worker-v1 uses data-only views; plugin functions never enter the UI thread. */
export type PluginNode =
  | string
  | null
  | {
      tag: string;
      text?: string;
      children?: PluginNode[];
      action?: string;
      value?: string;
      placeholder?: string;
      disabled?: boolean;
      path?: string;
      mode?: "preview" | "download" | "upload" | "upload-files";
      filename?: string;
    };

export interface PluginRegistration {
  id: string;
  kind: "route" | "tool";
  path?: string;
  label?: string;
  tool?: string;
}

const tags = new Set([
  "div",
  "section",
  "p",
  "span",
  "h1",
  "h2",
  "h3",
  "strong",
  "em",
  "ul",
  "ol",
  "li",
  "pre",
  "code",
  "button",
  "input",
  "label",
  "table",
  "thead",
  "tbody",
  "tr",
  "td",
  "th",
  "file-action",
]);

export function runtimePath(pluginId: string, value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^\/[a-zA-Z0-9_/?=&.%+-]*$/.test(value) ||
    /\.\.|%2e|%2f|%5c|%25/i.test(value.split("?")[0]) ||
    value.includes("//")
  ) {
    throw new Error("invalid_plugin_api_path");
  }
  return `/frontend_plugin/${encodeURIComponent(pluginId)}/runtime${value}`;
}

export function validateView(value: unknown): PluginNode {
  let count = 0,
    characters = 0;
  function visit(node: unknown, depth: number): PluginNode {
    if (++count > 1000 || depth > 20) throw new Error("plugin_view_too_large");
    if (node === null) return null;
    if (typeof node === "string") {
      characters += node.length;
      if (characters > 128_000) throw new Error("plugin_view_too_large");
      return node;
    }
    if (!node || typeof node !== "object" || Array.isArray(node))
      throw new Error("invalid_plugin_view");
    const item = node as Record<string, unknown>;
    if (typeof item.tag !== "string" || !tags.has(item.tag))
      throw new Error("invalid_plugin_tag");
    const result: Exclude<PluginNode, string | null> = { tag: item.tag };
    if (item.tag === "file-action") {
      if (
        !["preview", "download", "upload", "upload-files"].includes(
          String(item.mode),
        ) ||
        typeof item.path !== "string" ||
        item.path.length > 2048
      )
        throw new Error("invalid_plugin_file");
      runtimePath("validate", item.path);
      result.mode = item.mode as typeof result.mode;
      result.path = item.path;
      if (typeof item.filename === "string")
        result.filename = item.filename
          .replace(/[^\p{L}\p{N}_. -]/gu, "_")
          .slice(0, 120);
    }
    for (const field of ["text", "value", "placeholder", "action"] as const) {
      if (item[field] !== undefined) {
        if (typeof item[field] !== "string")
          throw new Error("invalid_plugin_attribute");
        characters += item[field].length;
        if (characters > 128_000) throw new Error("plugin_view_too_large");
        result[field] = item[field];
      }
    }
    if (item.disabled !== undefined) result.disabled = item.disabled === true;
    if (item.children !== undefined) {
      if (!Array.isArray(item.children))
        throw new Error("invalid_plugin_children");
      result.children = item.children.map((child) => visit(child, depth + 1));
    }
    return result;
  }
  return visit(value, 0);
}

/** Bound tool props before cloning; omit callbacks, cycles and React elements. */
export function pluginInput(input: unknown): unknown {
  let remaining = 1000;
  let characters = 128_000;
  const seen = new WeakSet<object>();
  const copy = (value: unknown, depth: number): unknown => {
    if (--remaining < 0 || depth > 12) return null;
    if (typeof value === "string") {
      const limit = Math.min(16000, characters);
      characters -= Math.min(value.length, limit);
      return value.length > limit ? value.slice(0, limit) + "…" : value;
    }
    if (
      value === null ||
      typeof value === "boolean" ||
      typeof value === "number"
    )
      return value;
    if (!value || typeof value !== "object" || seen.has(value)) return null;
    seen.add(value);
    if (Array.isArray(value))
      return value.slice(0, 100).map((item) => copy(item, depth + 1));
    if (Object.getPrototypeOf(value) !== Object.prototype) return null;
    return Object.fromEntries(
      Object.entries(value)
        .slice(0, 100)
        .filter(
          ([key, item]) => key !== "children" && typeof item !== "function",
        )
        .map(([key, item]) => [key, copy(item, depth + 1)]),
    );
  };
  return copy(input, 0);
}

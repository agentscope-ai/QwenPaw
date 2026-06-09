import type { HostBundle } from "../types";

function parseToolArgs(data: { content?: Array<{ data?: { arguments?: unknown } }> }) {
  const raw = data?.content?.[0]?.data?.arguments;
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw);
    } catch {
      return {};
    }
  }
  return (raw as Record<string, unknown>) ?? {};
}

function extractTitle(args: Record<string, unknown>): string {
  for (const key of ["query", "text", "question", "prompt"]) {
    const v = args[key];
    if (typeof v === "string" && v.trim()) return v;
  }
  for (const v of Object.values(args)) {
    if (typeof v === "string" && v.trim()) return v;
  }
  return "";
}

function parseOutput(output: unknown): {
  columns?: string[];
  data?: unknown[][];
  sql?: string;
} | null {
  if (!output) return null;
  let payload: unknown = output;
  if (typeof output === "string") {
    try {
      payload = JSON.parse(output);
    } catch {
      return null;
    }
  }
  if (Array.isArray(payload) && payload.length > 0) {
    const first = payload[0] as { text?: string };
    if (first?.text) {
      try {
        payload = JSON.parse(first.text);
      } catch {
        return null;
      }
    }
  }
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const p = payload as Record<string, unknown>;
    return {
      columns: Array.isArray(p.columns) ? (p.columns as string[]) : undefined,
      data: Array.isArray(p.data) ? (p.data as unknown[][]) : undefined,
      sql: typeof p.sql === "string" ? p.sql : undefined,
    };
  }
  return null;
}

export function createFetchDataRender(host: HostBundle) {
  const { React, antd } = host;
  const { Spin, Typography } = antd;
  const { Text } = Typography;

  return function FetchDataRender({
    data,
  }: {
    data: {
      status?: string;
      content?: Array<{
        data?: { name?: string; arguments?: unknown; output?: unknown };
      }>;
    };
  }) {
    const content = data?.content ?? [];
    const args = parseToolArgs(data);
    const title = extractTitle(args) || content[0]?.data?.name || "fetch_data";
    const rawOutput = content[1]?.data?.output;
    const parsed = parseOutput(rawOutput);
    const loading = data?.status === "IN_PROGRESS" || !rawOutput;

    if (loading && !parsed) {
      return React.createElement(
        "div",
        { style: { padding: "8px 0" } },
        React.createElement(Spin, { size: "small" }),
      );
    }

    const children: React.ReactNode[] = [
      React.createElement(
        Text,
        { key: "title", strong: true },
        `📊 ${title}`,
      ),
    ];

    if (parsed?.sql) {
      children.push(
        React.createElement(
          "pre",
          {
            key: "sql",
            style: {
              marginTop: 8,
              padding: 8,
              background: "#f5f5f5",
              borderRadius: 4,
              fontSize: 12,
              overflow: "auto",
            },
          },
          parsed.sql,
        ),
      );
    }

    if (parsed?.columns && parsed?.data) {
      children.push(
        React.createElement(
          "div",
          { key: "table", style: { marginTop: 8, overflow: "auto" } },
          React.createElement(
            "table",
            {
              style: {
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 12,
              },
            },
            React.createElement(
              "thead",
              null,
              React.createElement(
                "tr",
                null,
                parsed.columns.map((col, i) =>
                  React.createElement(
                    "th",
                    {
                      key: i,
                      style: {
                        borderBottom: "1px solid #eee",
                        textAlign: "left",
                        padding: "4px 8px",
                      },
                    },
                    col,
                  ),
                ),
              ),
            ),
            React.createElement(
              "tbody",
              null,
              parsed.data.slice(0, 20).map((row, rIdx) =>
                React.createElement(
                  "tr",
                  { key: rIdx },
                  (Array.isArray(row) ? row : [row]).map((cell, cIdx) =>
                    React.createElement(
                      "td",
                      {
                        key: cIdx,
                        style: {
                          borderBottom: "1px solid #f0f0f0",
                          padding: "4px 8px",
                        },
                      },
                      typeof cell === "object" && cell !== null
                        ? JSON.stringify(cell)
                        : String(cell ?? ""),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    }

    return React.createElement("div", { style: { padding: "4px 0" } }, children);
  };
}

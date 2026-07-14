import { describe, expect, it, vi } from "vitest";
import type { TFunction } from "i18next";
import { formatAgentList, formatMemorySearch } from "./utils";

vi.mock("@/api/modules/chat", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/modules/chat")>();
  return {
    ...actual,
    chatApi: {
      ...actual.chatApi,
      filePreviewUrl: vi.fn((p: string) => `http://localhost:8000${p}`),
    },
  };
});

const translate = ((key: string) => {
  const translations: Record<string, string> = {
    "tool.formatTable.file": "file",
    "tool.formatTable.lineNumber": "lineNumber",
    "tool.formatTable.score": "score",
    "tool.formatTable.summary": "summary",
    "tool.formatTable.name": "name",
    "tool.formatTable.id": "id",
    "tool.formatTable.description": "description",
    "tool.formatTable.status": "status",
  };

  return translations[key] ?? key;
}) as TFunction;

describe("formatMemorySearch", () => {
  it("renders memory search results as readable markdown cards", () => {
    const memoryResults = [
      {
        path: "memory/2026-06-08.md",
        start_line: 42,
        end_line: 45,
        score: 0.85,
        snippet: "这是实际摘要内容",
      },
    ];
    const rawToolResult = JSON.stringify([
      {
        type: "text",
        text: JSON.stringify(memoryResults),
      },
    ]);

    const formattedResult = formatMemorySearch(rawToolResult, translate);

    expect(formattedResult).toContain("### 1. memory/2026-06-08.md");
    expect(formattedResult).toContain("- **lineNumber**: L42-45");
    expect(formattedResult).toContain("- **score**: 0.85");
    expect(formattedResult).toContain("这是实际摘要内容");
    expect(formattedResult).not.toContain("| memory/2026-06-08.md |");
  });

  it("unwraps plain text tool result blocks instead of showing raw JSON", () => {
    const rawToolResult = JSON.stringify([
      {
        type: "text",
        text: "memory/2026-05-18.md L1-77\\n# 记忆与反思\\n这是很长的内容",
      },
    ]);

    const formattedResult = formatMemorySearch(rawToolResult, translate);

    expect(formattedResult).toBe(
      "memory/2026-05-18.md L1-77\n# 记忆与反思\n这是很长的内容",
    );
    expect(formattedResult).not.toContain('"type":"text"');
    expect(formattedResult).not.toContain("\\n");
  });

  it("formats malformed memory search text without showing metadata prefix", () => {
    // 截图格式：[ { 之间有空格，snippet 含真实换行导致 JSON.parse 失败
    const malformedMemoryText =
      '[ { "path": "/Users/zz/.copaw/workspaces/q88eWE/memory/2026-05-18.md", "start_line": 1, "end_line": 77, "score": 0.625, "snippet": "# 记忆与反思 - 2026-05-18\n\n## 项目信息\n\n项目名称：《弹幕逃生》4分钟短视频';
    const rawToolResult = JSON.stringify([
      {
        type: "text",
        text: malformedMemoryText,
      },
    ]);

    const formattedResult = formatMemorySearch(rawToolResult, translate);

    expect(formattedResult).toContain(
      "### 1. /Users/zz/.copaw/workspaces/q88eWE/memory/2026-05-18.md",
    );
    expect(formattedResult).toContain("- **lineNumber**: L1-77");
    expect(formattedResult).toContain("- **score**: 0.63");
    expect(formattedResult).toContain("# 记忆与反思 - 2026-05-18");
    expect(formattedResult).not.toContain('[ { "path"');
    expect(formattedResult).not.toContain('"snippet":');
  });
});

describe("formatAgentList", () => {
  it("renders agent rows from tool result text blocks", () => {
    const agents = [
      {
        name: "Coder",
        id: "agent-1",
        description: "Coding agent",
        status: "ready",
      },
    ];
    const rawToolResult = JSON.stringify([
      {
        type: "text",
        text: JSON.stringify(agents),
      },
    ]);

    const formattedResult = formatAgentList(rawToolResult, translate);

    expect(formattedResult).toContain(
      "| Coder | `agent-1` | Coding agent | ready |",
    );
    expect(formattedResult).not.toContain("|  | `` |  |  |");
  });
});

import { extractAllMediaFromResult, type MediaInfo } from "./utils";
import type { ToolCallContent } from "./types";

const makeContent = (
  result: unknown,
  params?: Record<string, unknown>,
): ToolCallContent => ({
  type: "tool_call",
  id: "test-id",
  name: "test_tool",
  params: params || {},
  result,
  status: "done",
});

describe("extractAllMediaFromResult", () => {
  it("returns empty array when no media is found", () => {
    expect(extractAllMediaFromResult(makeContent("plain text"))).toEqual([]);
  });

  it("extracts a single image from MCP content blocks", () => {
    const content = makeContent([
      { type: "image", source: { type: "url", url: "/uploads/img.png" } },
      { type: "text", text: "Here is the image" },
    ]);
    const media = extractAllMediaFromResult(content);
    expect(media).toHaveLength(1);
    expect(media[0].type).toBe("image");
    expect(media[0].name).toBe("img.png");
  });

  it("extracts multiple files from MCP content blocks", () => {
    const content = makeContent([
      { type: "image", source: { type: "url", url: "/uploads/a.png" } },
      {
        type: "file",
        source: { type: "url", url: "/uploads/b.pdf" },
        filename: "report.pdf",
      },
      { type: "video", source: { type: "url", url: "/uploads/c.mp4" } },
    ]);
    const media = extractAllMediaFromResult(content);
    expect(media).toHaveLength(3);
    expect(media.map((m: MediaInfo) => m.type)).toEqual([
      "image",
      "file",
      "video",
    ]);
  });

  it("parses JSON-string MCP blocks", () => {
    const content = makeContent(
      JSON.stringify([
        { type: "audio", source: { type: "url", url: "/uploads/sound.mp3" } },
      ]),
    );
    const media = extractAllMediaFromResult(content);
    expect(media).toHaveLength(1);
    expect(media[0].type).toBe("audio");
  });

  it("extracts path from plain text using saved-to pattern", () => {
    const content = makeContent("Image saved to /tmp/output.png");
    const media = extractAllMediaFromResult(content);
    expect(media).toHaveLength(1);
    expect(media[0].type).toBe("image");
  });

  it("falls back to params when result has no media", () => {
    const content = makeContent("done", { image_path: "/tmp/params.png" });
    const media = extractAllMediaFromResult(content);
    expect(media).toHaveLength(1);
    expect(media[0].type).toBe("image");
  });

  it("deduplicates by display URL", () => {
    const content = makeContent([
      { type: "image", source: { type: "url", url: "/uploads/img.png" } },
      { type: "text", text: "see /uploads/img.png" },
    ]);
    const media = extractAllMediaFromResult(content);
    expect(media).toHaveLength(1);
  });

  it("does not duplicate when params path differs from result block url", () => {
    const content = makeContent(
      JSON.stringify([
        {
          type: "image",
          source: { type: "url", url: "file:///Users/zz/Desktop/尾巴帧.jpg" },
        },
        { type: "text", text: "Image loaded: 尾巴帧.jpg" },
      ]),
      { image_path: "尾巴帧.jpg" },
    );
    const media = extractAllMediaFromResult(content);
    expect(media).toHaveLength(1);
    expect(media[0].name).toBe("尾巴帧.jpg");
    expect(media[0].rawUrl).toBe("file:///Users/zz/Desktop/尾巴帧.jpg");
  });

  it("preserves rawUrl on extracted media", () => {
    const content = makeContent("Image saved to /tmp/output.png");
    const media = extractAllMediaFromResult(content);
    expect(media).toHaveLength(1);
    expect(media[0].rawUrl).toBe("/tmp/output.png");
  });
});

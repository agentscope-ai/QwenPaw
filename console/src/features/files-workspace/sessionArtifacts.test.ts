import { describe, expect, it } from "vitest";
import {
  extractSessionArtifacts,
  SessionArtifactSseCollector,
} from "./sessionArtifacts";

describe("extractSessionArtifacts", () => {
  it("collects files written by WriteFile", () => {
    const artifacts = extractSessionArtifacts([
      {
        role: "assistant",
        cards: [
          {
            data: {
              output: [
                {
                  id: "call-summary",
                  type: "tool_call",
                  name: "write_file",
                  params: { file_path: "reports/summary.md" },
                },
                {
                  type: "tool_call_output",
                  status: "completed",
                  content: [
                    {
                      data: {
                        call_id: "call-summary",
                        name: "write_file",
                        state: "success",
                        output: "Successfully wrote summary.md",
                      },
                    },
                  ],
                },
              ],
            },
          },
        ],
      },
    ]);

    expect(artifacts).toHaveLength(1);
    expect(artifacts[0].name).toBe("summary.md");
    expect(artifacts[0].target).toMatchObject({
      source: "workspace",
      path: "reports/summary.md",
      root: "project",
    });
  });

  it("ignores user uploads and read-only tool calls", () => {
    const artifacts = extractSessionArtifacts([
      {
        role: "user",
        content: [{ type: "file", file_url: "/tmp/input.pdf" }],
      },
      {
        role: "assistant",
        content: [
          {
            type: "tool_call",
            name: "read_file",
            params: { file_path: "notes.txt" },
          },
        ],
      },
    ]);

    expect(artifacts).toEqual([]);
  });

  it("returns no artifacts for ordinary chat messages", () => {
    expect(
      extractSessionArtifacts([
        { role: "user", content: [{ type: "text", text: "hh" }] },
        {
          role: "assistant",
          content: [{ type: "text", text: "今天想聊点什么？" }],
        },
      ]),
    ).toEqual([]);
  });

  it("ignores paths mentioned by successful shell results", () => {
    expect(
      extractSessionArtifacts([
        {
          role: "assistant",
          content: [
            {
              id: "call-shell",
              type: "tool_call",
              name: "shell",
              params: {
                output_path: "temporary.md",
                command: "rm temporary.md",
              },
            },
            {
              type: "tool_call_output",
              call_id: "call-shell",
              status: "completed",
              content: [
                { type: "data", data: { state: "success", output: "" } },
              ],
            },
          ],
        },
      ]),
    ).toEqual([]);
  });

  it("does not publish a failed file tool call", () => {
    expect(
      extractSessionArtifacts([
        {
          role: "assistant",
          content: [
            {
              id: "call-failed",
              type: "tool_call",
              name: "write_file",
              params: { file_path: "failed.md" },
            },
            {
              type: "tool_call_output",
              status: "completed",
              content: [
                {
                  data: {
                    call_id: "call-failed",
                    name: "write_file",
                    state: "error",
                    output: "write failed",
                  },
                },
              ],
            },
          ],
        },
      ]),
    ).toEqual([]);
  });

  it("keeps only the latest occurrence of the same artifact", () => {
    const artifacts = extractSessionArtifacts([
      {
        role: "assistant",
        content: [
          {
            id: "call-write",
            type: "tool_call",
            name: "write_file",
            params: { file_path: "result.csv" },
          },
          {
            type: "tool_call_output",
            status: "completed",
            content: [
              {
                data: {
                  call_id: "call-write",
                  name: "write_file",
                  state: "success",
                  output: "written",
                },
              },
            ],
          },
          {
            id: "call-edit",
            type: "tool_call",
            name: "edit_file",
            params: { file_path: "result.csv" },
          },
          {
            type: "tool_call_output",
            status: "completed",
            content: [
              {
                data: {
                  call_id: "call-edit",
                  name: "edit_file",
                  state: "success",
                  output: "edited",
                },
              },
            ],
          },
        ],
      },
    ]);

    expect(artifacts).toHaveLength(1);
    expect(artifacts[0].toolName).toBe("edit_file");
  });

  it("accepts camel-case EditFile and AppendFile names", () => {
    const artifacts = extractSessionArtifacts([
      {
        role: "assistant",
        content: [
          {
            type: "tool_call",
            name: "EditFile",
            arguments: JSON.stringify({ file_path: "notes.md" }),
            result: "edited",
          },
          {
            type: "tool_call",
            name: "AppendFile",
            arguments: JSON.stringify({ file_path: "journal.md" }),
            result: "appended",
          },
        ],
      },
    ]);

    expect(artifacts.map((artifact) => artifact.name)).toEqual([
      "journal.md",
      "notes.md",
    ]);
  });

  it("ignores other producing tools and standalone assistant media", () => {
    expect(
      extractSessionArtifacts([
        {
          role: "assistant",
          content: [
            {
              type: "tool_call",
              name: "send_file_to_user",
              params: { file_path: "report.pdf" },
              result: "sent",
            },
            {
              type: "tool_call",
              name: "generate_image",
              params: { output_path: "chart.png" },
              result: "generated",
            },
            {
              type: "image",
              image_url: "/api/files/preview/chart.png",
              filename: "chart.png",
            },
          ],
        },
      ]),
    ).toEqual([]);
  });

  it("collects a file from the SDK message shape used by WriteFileCard", () => {
    const artifacts = extractSessionArtifacts([
      {
        id: "assistant-1",
        role: "assistant",
        cards: [
          {
            code: "AgentScopeRuntimeResponseCard",
            data: {
              output: [
                {
                  id: "call-write-story",
                  role: "assistant",
                  type: "tool_call",
                  status: "completed",
                  content: [
                    {
                      type: "data",
                      data: {
                        call_id: "call-write-story",
                        name: "write_file",
                        arguments: JSON.stringify({
                          file_path: "story.md",
                          content: "从前有一个故事。",
                        }),
                      },
                    },
                  ],
                },
                {
                  id: "output-write-story",
                  role: "tool",
                  type: "tool_call_output",
                  status: "completed",
                  content: [
                    {
                      type: "data",
                      data: {
                        call_id: "call-write-story",
                        name: "write_file",
                        state: "success",
                        output: "Successfully wrote 24 lines to story.md",
                      },
                    },
                  ],
                },
              ],
            },
          },
        ],
      },
    ]);

    expect(artifacts).toEqual([
      {
        id: "workspace:story.md",
        name: "story.md",
        path: "story.md",
        kind: "file",
        toolName: "write_file",
        target: {
          source: "workspace",
          path: "story.md",
          root: "project",
        },
      },
    ]);
  });
});

describe("SessionArtifactSseCollector", () => {
  it("publishes a file only after the streamed tool result succeeds", () => {
    const collector = new SessionArtifactSseCollector();
    collector.ingest({
      object: "message",
      id: "msg-write-story",
      type: "plugin_call",
      role: "assistant",
      status: "in_progress",
      content: [],
    });
    collector.ingest({
      object: "content",
      msg_id: "msg-write-story",
      index: 0,
      type: "data",
      delta: true,
      data: {
        call_id: "call-write-story",
        name: "write_file",
        arguments: "",
      },
    });

    expect(
      collector.ingest({
        object: "content",
        msg_id: "msg-write-story",
        index: 0,
        type: "data",
        delta: true,
        data: { arguments: '{"file_path":"story.md"}' },
      }),
    ).toEqual([]);

    collector.ingest({
      object: "message",
      id: "msg-write-result",
      type: "plugin_call_output",
      role: "tool",
      status: "in_progress",
      content: [],
    });
    expect(
      collector.ingest({
        object: "content",
        msg_id: "msg-write-result",
        index: 0,
        type: "data",
        delta: false,
        data: {
          call_id: "call-write-story",
          name: "write_file",
          state: "success",
          output: "Successfully wrote story.md",
        },
      }),
    ).toMatchObject([
      {
        name: "story.md",
        target: { source: "workspace", path: "story.md", root: "project" },
      },
    ]);
  });

  it("hydrates canonical response output without waiting for render state", () => {
    const collector = new SessionArtifactSseCollector();
    const artifacts = collector.ingest({
      object: "response",
      status: "completed",
      output: [
        {
          id: "call-report-message",
          type: "plugin_call",
          role: "assistant",
          content: [
            {
              type: "data",
              data: {
                call_id: "call-report",
                name: "write_file",
                arguments: '{"file_path":"reports/final.md"}',
              },
            },
          ],
        },
        {
          id: "result-report-message",
          type: "plugin_call_output",
          role: "tool",
          status: "completed",
          content: [
            {
              type: "data",
              data: {
                call_id: "call-report",
                name: "write_file",
                state: "success",
                output: "written",
              },
            },
          ],
        },
      ],
    });

    expect(artifacts[0]?.path).toBe("reports/final.md");
  });

  it("resets artifacts when the Session changes", () => {
    const collector = new SessionArtifactSseCollector();
    collector.ingest({
      object: "response",
      output: [
        {
          id: "call-old-message",
          type: "plugin_call",
          content: [
            {
              data: {
                call_id: "call-old",
                name: "write_file",
                arguments: '{"file_path":"old.md"}',
              },
            },
          ],
        },
        {
          id: "result-old-message",
          type: "plugin_call_output",
          status: "completed",
          content: [
            {
              data: {
                call_id: "call-old",
                name: "write_file",
                state: "success",
                output: "written",
              },
            },
          ],
        },
      ],
    });

    collector.reset();
    expect(collector.artifacts()).toEqual([]);
  });

  it("does not rebuild artifacts for ordinary text SSE events", () => {
    const collector = new SessionArtifactSseCollector();
    const current = collector.artifacts();

    collector.ingest({
      object: "message",
      id: "assistant-text",
      type: "message",
      role: "assistant",
      content: [],
    });
    const next = collector.ingest({
      object: "content",
      msg_id: "assistant-text",
      index: 0,
      type: "text",
      delta: true,
      text: "ordinary response",
    });

    expect(next).toBe(current);
  });
});

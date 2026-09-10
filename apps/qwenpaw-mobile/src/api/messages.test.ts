import assert from "node:assert/strict";
import test from "node:test";

import { toDisplayMessages, toDisplayTurns } from "./messages";

test("preserves reasoning and tool steps but selects the final answer", () => {
  const messages = toDisplayMessages([
    { id: "user", type: "message", role: "user", content: "开始" },
    { id: "thought", type: "reasoning", role: "assistant", content: "分析" },
    {
      id: "tool",
      type: "plugin_call",
      role: "assistant",
      content: [{ type: "data", data: { name: "web_search" } }],
    },
    { id: "draft", type: "message", role: "assistant", content: "中间内容" },
    { id: "answer", type: "message", role: "assistant", content: "最终答案" },
  ]);
  const [turn] = toDisplayTurns(messages);

  assert.equal(turn.answer?.id, "answer");
  assert.deepEqual(turn.process.map((message) => message.id), [
    "thought",
    "tool",
    "draft",
  ]);
});

test("preserves image video audio and file content", () => {
  const [message] = toDisplayMessages([{
    id: "media",
    type: "message",
    role: "assistant",
    content: [
      { type: "text", text: "附件" },
      { type: "image", image_url: "/tmp/a.png" },
      { type: "video", video_url: "https://example.com/a.mp4" },
      { type: "audio", data: "/tmp/a.wav" },
      { type: "file", file_url: "/tmp/a.pdf", filename: "a.pdf" },
    ],
  }]);

  assert.deepEqual(message.parts.map((part) => part.type), [
    "text",
    "image",
    "video",
    "audio",
    "file",
  ]);
});

test("extracts media from tool result blocks into the answer turn", () => {
  const messages = toDisplayMessages([
    { id: "user", type: "message", role: "user", content: "截图" },
    {
      id: "result",
      type: "plugin_call_output",
      role: "tool",
      content: [{
        type: "data",
        data: {
          name: "desktop_screenshot",
          output: JSON.stringify([{
            type: "image",
            source: { type: "url", url: "/tmp/screen.png" },
            filename: "screen.png",
          }]),
        },
      }],
    },
    { id: "answer", type: "message", role: "assistant", content: "已发送" },
  ]);
  const [turn] = toDisplayTurns(messages);

  assert.deepEqual(turn.resultMedia, [{
    type: "image",
    url: "/tmp/screen.png",
    name: "screen.png",
  }]);
});

test("redacts sensitive tool parameters from display details", () => {
  const [message] = toDisplayMessages([{
    id: "call",
    type: "plugin_call",
    role: "assistant",
    content: [{
      type: "data",
      data: {
        name: "request",
        arguments: JSON.stringify({ token: "private", query: "hello" }),
      },
    }],
  }]);

  assert.doesNotMatch(message.toolInput ?? "", /private/);
  assert.match(message.toolInput ?? "", /hello/);
});

test("extracts screenshot paths from tool arguments and text results", () => {
  const messages = toDisplayMessages([
    { id: "user", type: "message", role: "user", content: "截图" },
    {
      id: "call",
      type: "plugin_call",
      role: "assistant",
      content: [{
        type: "data",
        data: {
          name: "send_file_to_user",
          arguments: JSON.stringify({
            file_path: "/Users/ray/workspace/desktop_screenshot.png",
          }),
        },
      }],
    },
    {
      id: "result",
      type: "plugin_call_output",
      role: "assistant",
      content: [{
        type: "data",
        data: {
          name: "desktop_screenshot",
          output: JSON.stringify([{
            type: "text",
            text: "Desktop screenshot saved to /Users/ray/workspace/desktop_screenshot.png",
          }]),
        },
      }],
    },
    { id: "answer", type: "message", role: "assistant", content: "已发送" },
  ]);
  const [turn] = toDisplayTurns(messages);

  assert.match(messages[1].toolInput ?? "", /desktop_screenshot\.png/);
  assert.match(messages[2].toolOutput ?? "", /Desktop screenshot saved/);
  assert.deepEqual(turn.resultMedia, [{
    type: "image",
    url: "/Users/ray/workspace/desktop_screenshot.png",
    name: "desktop_screenshot.png",
  }]);
});

test("drops only empty normal messages", () => {
  assert.deepEqual(toDisplayMessages([
    { id: "empty", type: "message", role: "assistant", content: [] },
  ]), []);
});

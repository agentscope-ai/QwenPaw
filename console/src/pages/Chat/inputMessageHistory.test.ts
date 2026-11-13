import { expect, it } from "vitest";
import type { IAgentScopeRuntimeWebUIMessage as Message } from "@agentscope-ai/chat";
import { getInputHistoryTexts } from "./inputMessageHistory";
import {
  createHistoryMessageWindowCard,
  type HistoryWindowSnapshot,
} from "./historyMessageWindowStore";

const user = (id: string, text: string) =>
  ({
    id,
    role: "user",
    cards: [
      {
        code: "User",
        data: { input: [{ content: [{ type: "text", text }] }] },
      },
    ],
  }) as Message;
const history = (rows: Message[][]) =>
  ({ sessionId: "chat-a", turnRows: rows }) as HistoryWindowSnapshot;

it("unwraps the host history card and merges live inputs without duplicates", () => {
  const first = user("one", "Full input\nsecond line");
  const second = user("two", "live input");
  expect(
    getInputHistoryTexts(
      [createHistoryMessageWindowCard("chat-a"), first, second],
      history([[first]]),
    ),
  ).toEqual(["Full input\nsecond line", "live input"]);
});
it("does not reuse another session or an earlier same-size history window", () => {
  const card = createHistoryMessageWindowCard("chat-a");
  expect(getInputHistoryTexts([card], history([[user("a", "older")]]))).toEqual(
    ["older"],
  );
  expect(getInputHistoryTexts([card], history([[user("b", "newer")]]))).toEqual(
    ["newer"],
  );
  expect(
    getInputHistoryTexts(
      [createHistoryMessageWindowCard("chat-b")],
      history([[user("a", "private")]]),
    ),
  ).toEqual([]);
});
it("preserves repeated inputs and skips assistants and attachment-only inputs", () => {
  expect(
    getInputHistoryTexts(
      [
        user("a", "repeat"),
        user("b", "repeat"),
        user("empty", ""),
        { id: "reply", role: "assistant", cards: [] } as Message,
      ],
      null,
    ),
  ).toEqual(["repeat", "repeat"]);
});

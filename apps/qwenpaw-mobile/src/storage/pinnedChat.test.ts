import assert from "node:assert/strict";
import test from "node:test";

import type { ChatSpec } from "../api/types";
import { sortChatsByPinned } from "./pinnedChat";

const chats: ChatSpec[] = [
  { id: "first", session_id: "one", user_id: "mobile", channel: "console" },
  { id: "second", session_id: "two", user_id: "mobile", channel: "console" },
  { id: "third", session_id: "three", user_id: "mobile", channel: "console" },
];

test("sortChatsByPinned moves the selected chat to the front", () => {
  assert.deepEqual(
    sortChatsByPinned(chats, "third").map((chat) => chat.id),
    ["third", "first", "second"],
  );
});

test("sortChatsByPinned keeps server order without a valid pin", () => {
  assert.deepEqual(sortChatsByPinned(chats, null), chats);
  assert.deepEqual(sortChatsByPinned(chats, "missing"), chats);
});

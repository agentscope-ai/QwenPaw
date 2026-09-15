import { expect, it } from "vitest";
import {
  AgentScopeRuntimeSessionTimeline,
  applyTimelinePatch,
} from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Timeline/Session";
import { toTimelineEvents } from "../sessionApi";

it("keeps stable history deliveries once and preserves repeated user turns", () => {
  const timeline = new AgentScopeRuntimeSessionTimeline();
  let view: any[] = [];
  timeline.subscribe((patch) => {
    view = applyTimelinePatch(view, patch);
  });
  const user = {
    id: "spoken-1:0",
    role: "user",
    type: "message",
    status: "completed",
    content: [{ type: "text", text: "same words" }],
    metadata: { original_id: "spoken-1", timeline_order: 1 },
  } as any;
  const assistant = {
    ...user,
    id: "spoken-1_assistant:0",
    role: "assistant",
    content: [{ type: "text", text: "answer" }],
    metadata: { original_id: "spoken-1_assistant", timeline_order: 1 },
  };
  const second = {
    ...user,
    id: "spoken-2:0",
    metadata: { original_id: "spoken-2", timeline_order: 2 },
  };
  timeline.appendImmutable(toTimelineEvents([user]) as any);
  timeline.appendImmutable(toTimelineEvents([user, assistant]) as any);
  timeline.appendImmutable(toTimelineEvents([second]) as any);
  expect(view.filter((item) => item.id === user.id)).toHaveLength(1);
  expect(view.filter((item) => item.id === second.id)).toHaveLength(1);
  expect(view).toHaveLength(3);
  const keys = view.map((item) => item.id);
  timeline.acceptHistory(
    timeline.beginHistory(true),
    toTimelineEvents([user, assistant, second]) as any,
  );
  expect(view.map((item) => item.id)).toEqual(keys);
});

it("uses the built SDK for history, live text, staged replay and handover", () => {
  const timeline = new AgentScopeRuntimeSessionTimeline();
  let view: any[] = [];
  timeline.subscribe((patch) => {
    view = applyTimelinePatch(view, patch);
  });
  const history = toTimelineEvents([
    {
      id: "answer",
      role: "assistant",
      type: "message",
      status: "completed",
      content: [{ type: "text", text: "prefix" }],
      metadata: { timeline_group_id: "task", timeline_order: 2 },
    } as any,
  ]) as any;
  timeline.acceptHistory(timeline.beginHistory(), history);
  const live = timeline.open("run", false);
  timeline.receive(live, {
    ...history[0],
    status: "in_progress",
    content: [],
    sequence_number: 1,
  });
  timeline.receive(live, {
    object: "content",
    type: "text",
    msg_id: "answer",
    text: "prefix-new",
    delta: true,
    sequence_number: 2,
  } as any);
  const text = () =>
    view
      .flatMap((m) => m.cards)
      .flatMap((c) => c.data.output || [])
      .flatMap((m) => m.content)
      .map((c) => c.text)
      .join("");
  expect(text()).toBe("prefix-new");
  const keys = view.map((m) => m.id);
  const replay = timeline.open("run", true);
  timeline.receive(replay, { ...history[0], content: [], sequence_number: 1 });
  expect(text()).toBe("prefix-new");
  timeline.receive(replay, {
    object: "content",
    type: "text",
    msg_id: "answer",
    text: "prefix-new",
    delta: true,
    sequence_number: 2,
  } as any);
  timeline.replayEnd(replay);
  expect(text()).toBe("prefix-new");
  timeline.seal("run", "saved");
  timeline.acceptHistory(timeline.beginHistory(true), [
    { ...history[0], content: [{ type: "text", text: "prefix-new" }] },
  ]);
  expect(text()).toBe("prefix-new");
  expect(view.map((m) => m.id)).toEqual(keys);
});

import { describe, expect, it, vi } from "vitest";
import { openCreatorEvents } from "@/api/creator/events";

const FILE_RUNTIME_EVENT_TYPES = [
  "command.queued",
  "agent.run.started",
  "agent.run.completed",
  "agent.run.failed",
  "agent.run.cancelled",
  "agent.assistant_message",
  "agent.tool.started",
  "agent.tool.completed",
  "agent.tool.failed",
  "agent.review.resolved",
  "agent.interrupt.idle",
] as const;

describe("Creator event stream", () => {
  it("consumes every file-native Runtime event as a named SSE event", () => {
    const onEvent = vi.fn();
    const stream = openCreatorEvents("p1", 0, onEvent);
    const sources = (
      globalThis as unknown as {
        __testEventSources: Array<{
          emit: (type: string, value: unknown) => void;
        }>;
      }
    ).__testEventSources;
    const source = sources.at(-1)!;

    FILE_RUNTIME_EVENT_TYPES.forEach((type, index) => {
      source.emit(type, {
        eventId: `file-event-${index + 1}`,
        seq: index + 1,
        type,
        projectId: "p1",
        creatorSessionId: "session-p1",
        at: "now",
        data: {},
      });
    });

    expect(onEvent.mock.calls.map(([event]) => event.type)).toEqual(
      FILE_RUNTIME_EVENT_TYPES,
    );
    stream.close();
  });
});

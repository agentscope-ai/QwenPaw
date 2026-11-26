import { describe, expect, it } from "vitest";

import {
  buildFallbackSystemMessage,
  buildMediaOmittedSystemMessage,
  mediaOmittedNoticeKey,
  modelFallbackEventKey,
  parseMediaOmittedNotice,
  parseModelFallbackEvents,
} from "./fallbackNotice";

const event = {
  type: "model_fallback" as const,
  from_provider_id: "openai",
  from_model_id: "gpt-primary",
  to_provider_id: "anthropic",
  to_model_id: "claude-fallback",
  reason_kind: "rate_limited",
};

describe("fallbackNotice", () => {
  it("parses direct and nested response metadata", () => {
    expect(
      parseModelFallbackEvents({
        metadata: { qwenpaw_model_fallbacks: [event] },
      }),
    ).toEqual([event]);
    expect(
      parseModelFallbackEvents({
        metadata: {
          metadata: { qwenpaw_model_fallbacks: [event] },
        },
      }),
    ).toEqual([event]);
  });

  it("rejects malformed events and creates stable deduplication keys", () => {
    expect(
      parseModelFallbackEvents({
        metadata: {
          qwenpaw_model_fallbacks: [{ type: "model_fallback" }, event],
        },
      }),
    ).toEqual([event]);
    expect(modelFallbackEventKey(event)).toBe(modelFallbackEventKey(event));
  });

  it("builds the system message rendered into the completed response", () => {
    expect(
      buildFallbackSystemMessage([event], (item) =>
        [
          `${item.from_provider_id}:${item.from_model_id}`,
          `${item.to_provider_id}:${item.to_model_id}`,
          item.reason_kind,
        ].join(" -> "),
      ),
    ).toEqual({
      type: "message",
      role: "system",
      content: [
        {
          type: "text",
          text: "openai:gpt-primary -> anthropic:claude-fallback -> rate_limited",
        },
      ],
      metadata: { qwenpaw_model_fallbacks: [event] },
    });
  });

  it("parses the media-omission summary from direct and nested metadata", () => {
    const notice = { count: 3, reason: "provider media limit" };
    expect(
      parseMediaOmittedNotice({
        metadata: { qwenpaw_media_omitted: notice },
      }),
    ).toEqual(notice);
    expect(
      parseMediaOmittedNotice({
        metadata: { metadata: { qwenpaw_media_omitted: notice } },
      }),
    ).toEqual(notice);
  });

  it("rejects an empty or malformed media-omission summary", () => {
    expect(parseMediaOmittedNotice({})).toBeNull();
    expect(
      parseMediaOmittedNotice({
        metadata: { qwenpaw_media_omitted: { count: 0 } },
      }),
    ).toBeNull();
    expect(
      parseMediaOmittedNotice({
        metadata: { qwenpaw_media_omitted: { count: -1 } },
      }),
    ).toBeNull();
    expect(
      parseMediaOmittedNotice({
        metadata: { qwenpaw_media_omitted: { count: "3" } },
      }),
    ).toBeNull();
    expect(
      parseMediaOmittedNotice({
        metadata: { qwenpaw_media_omitted: "3 items" },
      }),
    ).toBeNull();
  });

  it("builds the media-omission system message", () => {
    const notice = { count: 2, reason: "" };
    expect(
      buildMediaOmittedSystemMessage(notice, "2 media items did not arrive"),
    ).toEqual({
      type: "message",
      role: "system",
      content: [{ type: "text", text: "2 media items did not arrive" }],
      metadata: { qwenpaw_media_omitted: notice },
    });
    expect(mediaOmittedNoticeKey(notice)).toBe("2:");
    expect(mediaOmittedNoticeKey({ count: 2, reason: "x" })).toBe("2:x");
  });
});

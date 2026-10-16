import {
  AgentScopeRuntimeContentType,
  Bubble,
  type IAgentScopeRuntimeMessage,
} from "@agentscope-ai/chat";
import React, { useMemo } from "react";

/**
 * #8203 — Renders a user-message echo projected into the live stream.
 *
 * When a turn is started from another client (mobile app, another tab),
 * the backend history does not contain the user turn until generation
 * completes, and this view's history layer is frozen while a turn is
 * active (applySessionView no-ops on an active turn). The response parser
 * therefore projects the echoed user message into the in-flight response
 * as a `user_echo` message frame (role "user"). The SDK's default card
 * renderer ignores unknown message types, so the `response.render` slot
 * draws each of those frames with this bubble — the same SDK `Bubble`
 * with `role="user"` the request card uses, so attached views match the
 * originating view's styling.
 *
 * Once the turn is persisted and the view refetches history, the user
 * card comes from history and the echo frame no longer exists.
 */
type EchoCard = { code: string; data: unknown };

function buildEchoCards(
  message: IAgentScopeRuntimeMessage,
): EchoCard[] {
  const content = message.content ?? [];
  const cards: EchoCard[] = [];
  for (const c of content) {
    switch (c?.type) {
      case AgentScopeRuntimeContentType.TEXT: {
        const text = c.text;
        if (typeof text === "string" && text.length > 0) {
          cards.push({ code: "Text", data: { content: text, raw: true } });
        }
        break;
      }
      case AgentScopeRuntimeContentType.IMAGE:
        if (c.image_url) {
          cards.push({ code: "Images", data: [{ url: c.image_url }] });
        }
        break;
      case AgentScopeRuntimeContentType.FILE:
        if (c.file_url) {
          cards.push({
            code: "Files",
            data: [
              {
                url: c.file_url,
                name: c.file_name || c.fileName || "file",
                size: c.file_size,
              },
            ],
          });
        }
        break;
      case AgentScopeRuntimeContentType.VIDEO:
        if (c.video_url) {
          cards.push({
            code: "Videos",
            data: [{ src: c.video_url, poster: c.video_poster }],
          });
        }
        break;
      case AgentScopeRuntimeContentType.AUDIO:
        if (c.audio_url || c.data) {
          cards.push({
            code: "Audios",
            data: [{ src: c.audio_url || String(c.data) }],
          });
        }
        break;
      default:
        break;
    }
  }
  return cards;
}

const UserEchoBubble = React.memo(function UserEchoBubble({
  data,
}: {
  data: IAgentScopeRuntimeMessage;
}) {
  const cards = useMemo(() => buildEchoCards(data), [data]);
  if (cards.length === 0) return null;
  return <Bubble role="user" cards={cards} />;
});

export default UserEchoBubble;

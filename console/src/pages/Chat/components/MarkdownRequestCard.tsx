import { useMemo } from "react";
import { Bubble } from "@agentscope-ai/chat";
import {
  requestContentToCards,
  type RuntimeRequest,
} from "./MarkdownRequestCard.utils";

export default function MarkdownRequestCard(props: { data: RuntimeRequest }) {
  const cards = useMemo(
    () => requestContentToCards(props.data.input[0]?.content || []),
    [props.data.input],
  );

  if (!cards.length) return null;

  return <Bubble role="user" cards={cards} />;
}

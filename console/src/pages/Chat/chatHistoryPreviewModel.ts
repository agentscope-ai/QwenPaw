import type { Message } from "../../api/types";

export interface PreviewTurn {
  user?: Message;
  output: Message[];
}

export function groupPreviewTurns(messages: Message[]): PreviewTurn[] {
  const turns: PreviewTurn[] = [];
  for (const message of messages) {
    if (message.role === "user") {
      turns.push({ user: message, output: [] });
      continue;
    }
    const turn = turns[turns.length - 1];
    if (turn) turn.output.push(message);
    else turns.push({ output: [message] });
  }
  return turns;
}

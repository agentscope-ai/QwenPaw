import { createElement } from "react";
import { message, notification } from "antd";

/**
 * Backend `userMessage` strings can be multi-line and long; antd's `message`
 * toast truncates them to a single line (v2.0.6 user feedback: the 409
 * authorization conflict was cut off mid-sentence). Route anything longer
 * than one short line to a notification, which stays until dismissed and
 * renders the full text with preserved line breaks.
 */

export type BackendFeedbackType = "success" | "error" | "warning" | "info";

const SINGLE_LINE_LIMIT = 40;

export function showBackendFeedback(
  type: BackendFeedbackType,
  text: string,
  title?: string,
): void {
  const normalized = text.trim();
  if (!normalized) return;
  if (!normalized.includes("\n") && normalized.length <= SINGLE_LINE_LIMIT) {
    message[type](normalized);
    return;
  }
  const [firstLine] = normalized.split("\n");
  notification[type]({
    message: title ?? firstLine.slice(0, SINGLE_LINE_LIMIT),
    description: createElement(
      "span",
      { style: { whiteSpace: "pre-line" } },
      normalized,
    ),
    duration: 0,
  });
}

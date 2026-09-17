import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export type UserInputQuestionKind =
  | "single_choice"
  | "free_text"
  | "choice_with_custom";

export type UserInputStatus =
  | "pending"
  | "answered"
  | "ignored"
  | "timeout"
  | "cancelled";

export interface UserInputOption {
  label: string;
  value: string;
  description?: string | null;
  recommended?: boolean;
}

export interface UserInputQuestion {
  id: string;
  question: string;
  kind: UserInputQuestionKind;
  options: UserInputOption[];
  placeholder?: string | null;
  required: boolean;
  default_value?: string | null;
}

export interface UserInputRequest {
  request_id: string;
  agent_id: string;
  session_id: string;
  root_session_id: string;
  user_id: string;
  channel: string;
  title?: string | null;
  questions: UserInputQuestion[];
  question_index: number;
  total_questions: number;
  status: UserInputStatus;
  created_at: number;
  timeout_seconds: number;
}

export interface UserInputAnswerPayload {
  answers: Record<string, unknown>;
  action: "submit" | "ignore" | "cancel";
}

export const userInputApi = {
  getPending: (sessionId: string) =>
    request<UserInputRequest | null>(
      `/user-input/pending?session_id=${encodeURIComponent(sessionId)}`,
    ),

  answer: (requestId: string, body: UserInputAnswerPayload) =>
    request<UserInputRequest>(`/user-input/${requestId}/answer`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export function subscribeUserInputUpdates(
  onUpdate: (
    request: UserInputRequest | null,
    sessionId: string | undefined,
    rootSessionId: string | undefined,
  ) => void,
  onError?: (err: unknown) => void,
): () => void {
  let aborted = false;
  const controller = new AbortController();

  async function connect() {
    while (!aborted) {
      try {
        const response = await fetch(getApiUrl("/user-input/stream"), {
          headers: buildAuthHeaders(),
          signal: controller.signal,
        });

        if (!response.ok || !response.body) {
          throw new Error(`SSE connect failed: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!aborted) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const data = JSON.parse(line.slice(6));
              if (
                data.type === "user_input_request" ||
                data.type === "user_input_update"
              ) {
                const next =
                  data.request?.status === "pending" ? data.request : null;
                onUpdate(next, data.session_id, data.root_session_id);
              }
            } catch {
              // ignore malformed event payloads
            }
          }
        }
      } catch (err) {
        if (aborted) return;
        onError?.(err);
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
    }
  }

  connect();

  return () => {
    aborted = true;
    controller.abort();
  };
}

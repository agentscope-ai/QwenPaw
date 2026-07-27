/**
 * Questionnaire API module
 *
 * Thin wrapper over the backend ``/api/questionnaire/submit`` endpoint
 * used by ``AskUserQuestionCard``.
 *
 * Backend truth source: ``src/qwenpaw/app/routers/questionnaire.py`` and
 * ``src/qwenpaw/app/questionnaires/models.py``.  Both must agree on the
 * public payload shape (session_id, status, …).
 *
 * Active cancellation goes through the Python ``QuestionService.cancel``
 * API (used by ``QuestionnaireCleanupHook``); debug listings use
 * ``GET /api/questionnaire/list`` directly.  Neither is exposed here —
 * there is no first-party frontend consumer for them yet.
 */

import { request } from "../request";

/** Question kinds accepted by the backend questionnaire renderer. */
export type QuestionType = "SINGLE_SELECT" | "MULTI_SELECT" | "TEXT_INPUT";

/** Single question definition. */
export interface Question {
  question_type: QuestionType;
  prompt: string;
  options?: (string | Record<string, unknown>)[];
}

/** Single answer payload. */
export interface Answer {
  question_index: number;
  answer: string;
  supplementary_input?: string;
}

/**
 * Lifecycle states a questionnaire can be in.  Mirrors the backend
 * ``QuestionnaireStatus`` StrEnum — keep in sync with
 * ``src/qwenpaw/app/questionnaires/models.py``.
 */
export type QuestionnaireStatus =
  | "pending"
  | "completed"
  | "timeout"
  | "cancelled"
  | "interrupted";

/** Submit-answer request payload. */
export interface SubmitAnswerRequest {
  session_id: string;
  answers: Answer[];
}

/** Response from ``POST /questionnaire/submit``. */
export interface SubmitAnswerResponse {
  success: boolean;
  message: string;
  session_id: string;
}

/**
 * Submit answers for the given session.  Returns 200 on success, 404
 * if no active questionnaire exists for that session.
 */
export async function submitQuestionnaireAnswer(
  data: SubmitAnswerRequest,
): Promise<SubmitAnswerResponse> {
  return request<SubmitAnswerResponse>("/questionnaire/submit", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

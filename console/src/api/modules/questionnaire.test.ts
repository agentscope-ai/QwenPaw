/**
 * Tests for api/modules/questionnaire.ts
 *
 * Contract-guard style: verify the request URL/method/body and the
 * return-value pass-through of ``submitQuestionnaireAnswer``.
 * 404 (questionnaire expired) is exercised because the card relies on
 * that branch to surface a warning.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { submitQuestionnaireAnswer } from "./questionnaire";
import { request } from "../request";

describe("submitQuestionnaireAnswer", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("POSTs the JSON payload to /questionnaire/submit", async () => {
    vi.mocked(request).mockResolvedValue({
      success: true,
      message: "ok",
      session_id: "s-1",
    });

    const payload = {
      session_id: "s-1",
      answers: [
        { question_index: 0, answer: "A" },
        { question_index: 1, answer: "B", supplementary_input: "extra" },
      ],
    };
    await submitQuestionnaireAnswer(payload);

    expect(request).toHaveBeenCalledWith(
      "/questionnaire/submit",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
      }),
    );
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("resolves with the server response on success", async () => {
    const response = {
      success: true,
      message: "submitted",
      session_id: "s-42",
    };
    vi.mocked(request).mockResolvedValue(response);

    const result = await submitQuestionnaireAnswer({
      session_id: "s-42",
      answers: [],
    });
    expect(result).toEqual(response);
  });

  it("propagates rejection from request() (e.g. 404 = questionnaire expired)", async () => {
    const expired = new Error("Questionnaire not found - 404");
    vi.mocked(request).mockRejectedValue(expired);

    await expect(
      submitQuestionnaireAnswer({
        session_id: "s-gone",
        answers: [{ question_index: 0, answer: "A" }],
      }),
    ).rejects.toBe(expired);
  });

  it("preserves the per-question answer shape (string answer, optional supplementary_input)", async () => {
    vi.mocked(request).mockResolvedValue({
      success: true,
      message: "ok",
      session_id: "s-1",
    });

    const answers = [
      { question_index: 0, answer: "yes" },
      { question_index: 1, answer: "custom reason", supplementary_input: "" },
      { question_index: 2, answer: "x", supplementary_input: "context" },
    ];
    await submitQuestionnaireAnswer({ session_id: "s-1", answers });

    expect(request).toHaveBeenCalledWith(
      "/questionnaire/submit",
      expect.objectContaining({
        body: JSON.stringify({ session_id: "s-1", answers }),
      }),
    );
  });

  it("accepts an empty answers array (no questions answered)", async () => {
    vi.mocked(request).mockResolvedValue({
      success: true,
      message: "ok",
      session_id: "s-1",
    });

    await submitQuestionnaireAnswer({ session_id: "s-1", answers: [] });

    expect(request).toHaveBeenCalledWith(
      "/questionnaire/submit",
      expect.objectContaining({
        body: JSON.stringify({ session_id: "s-1", answers: [] }),
      }),
    );
  });
});

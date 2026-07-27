/**
 * AskUserQuestionCard — tests.
 *
 * Conventions:
 *   - `renderWithProviders` wraps the component in `App` + `MemoryRouter`
 *     (antd message instance etc.).
 *   - `react-i18next` is stubbed so `t(key, fallback)` returns `fallback`.
 *     The component's English fallback strings are the assertion target.
 *   - `submitQuestionnaireAnswer` is stubbed to avoid network calls.
 *
 * Coverage:
 *   - Parse fallback (invalid JSON / empty result / wrapped JSON / markdown fences)
 *   - ErrorBoundary degrade + reset on content change
 *   - Done result rendering (completed / timeout / cancelled / interrupted / error)
 *   - Form interactions: option selection, Other input, Next/Back/Submit
 *   - Submission flow: success + 404 expiry warning + generic failure
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { AskUserQuestionCard } from "./AskUserQuestionCard";
import type { ToolCallContent } from "../../shared/types";

// vi.hoisted: variables must be initialised before vi.mock is hoisted.
const { mockSubmit, mockWriteText } = vi.hoisted(() => ({
  mockSubmit: vi.fn().mockResolvedValue(undefined),
  mockWriteText: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    // Return English fallback so component text is deterministic in tests.
    // Supports ``{{var}}`` interpolation for ``fallback``-string patterns the
    // component emits via t(key, fallback, options).
    t: (
      _key: string,
      fallback?: string | unknown,
      options?: Record<string, unknown>,
    ) => {
      if (typeof fallback !== "string") return _key;
      if (!options) return fallback;
      return fallback.replace(/\{\{(\w+)\}\}/g, (_m, k: string) =>
        options[k] === undefined ? `{{${k}}}` : String(options[k]),
      );
    },
    i18n: { language: "en", changeLanguage: vi.fn() },
  }),
}));

vi.mock("../../../../../api/modules/questionnaire", () => ({
  submitQuestionnaireAnswer: mockSubmit,
}));

// Clipboard mock — copy button uses navigator.clipboard.writeText.
Object.defineProperty(navigator, "clipboard", {
  configurable: true,
  value: { writeText: mockWriteText },
});

// ── fixtures ────────────────────────────────────────────────────────

function buildContent(
  status: "calling" | "done" | "error",
  result: unknown,
  questions?: string,
): ToolCallContent {
  return {
    type: "tool_call",
    id: "test-id",
    name: "ask_user_question",
    status,
    params: { questions: questions ?? "[]" },
    result,
  };
}

const doneContent = (result: unknown, questions?: string) =>
  buildContent("done", result, questions);
const errorContent = (result: unknown, questions?: string) =>
  buildContent("error", result, questions);
const callingContent = (questions?: string) =>
  buildContent("calling", undefined, questions);

beforeEach(() => {
  mockSubmit.mockClear();
  mockWriteText.mockClear();
  // Provide a session id so the submit path can run.
  (window as unknown as { currentSessionId?: string }).currentSessionId =
    "test-session";
});

afterEach(() => {
  cleanup();
});

// ── parse fallback (KI-8) ───────────────────────────────────────────

describe("AskUserQuestionCard — parse fallback", () => {
  it("degrades to fallback text card when result is invalid JSON", () => {
    renderWithProviders(
      <AskUserQuestionCard content={doneContent("not a valid json")} />,
    );
    expect(
      screen.getByText(/The questionnaire result could not be parsed/),
    ).toBeInTheDocument();
  });

  it("degrades to fallback text card when result is empty string", () => {
    renderWithProviders(<AskUserQuestionCard content={doneContent("")} />);
    expect(
      screen.getByText(/The questionnaire result could not be parsed/),
    ).toBeInTheDocument();
    // Copy button always rendered on the fallback card.
    expect(
      screen.getByRole("button", { name: /Copy raw data/ }),
    ).toBeInTheDocument();
  });

  it("tolerates LLM-returned JSON wrapped in surrounding prose", () => {
    const questions =
      'Here is the JSON: [{"prompt":"Q1?","question_type":"SINGLE_SELECT","options":["A"]}] thanks';
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );
    expect(screen.getByText("Q1?")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "A" })).toBeInTheDocument();
  });

  it("tolerates LLM-returned JSON double-wrapped in quotes", () => {
    const questions =
      '"[{\\"prompt\\":\\"Q1?\\",\\"question_type\\":\\"SINGLE_SELECT\\",\\"options\\":[\\"A\\"]}]"';
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );
    expect(screen.getByText("Q1?")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "A" })).toBeInTheDocument();
  });

  it("tolerates LLM-returned JSON inside markdown code fences", () => {
    const questions =
      '```json\n[{"prompt":"Q1?","question_type":"SINGLE_SELECT","options":["A"]}]\n```';
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );
    expect(screen.getByText("Q1?")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "A" })).toBeInTheDocument();
  });
});

// ── done result rendering (KI-9) ────────────────────────────────────

describe("AskUserQuestionCard — done result rendering", () => {
  it("renders question index, prompt, and per-question answer in order", () => {
    const questions = JSON.stringify([
      { prompt: "Favorite color?" },
      { prompt: "Given name?" },
    ]);
    const result = JSON.stringify({
      status: "completed",
      answers: [
        { question: "Favorite color?", answer: "red" },
        { question: "Given name?", answer: "" },
      ],
    });

    renderWithProviders(
      <AskUserQuestionCard content={doneContent(result, questions)} />,
    );

    expect(screen.getByText(/1\. Favorite color\?/)).toBeInTheDocument();
    expect(screen.getByText(/2\. Given name\?/)).toBeInTheDocument();
    expect(screen.getByText("red")).toBeInTheDocument();
    expect(screen.getByText(/Unanswered/)).toBeInTheDocument();
  });

  it.each([
    ["timeout", /Timed out/],
    ["cancelled", /Cancelled/],
    ["interrupted", /Interrupted/],
  ])(
    "renders the question table with status badge for %s",
    (status, badgeRegex) => {
      const questions = JSON.stringify([{ prompt: "Favorite color?" }]);
      const result = JSON.stringify({
        status,
        answers: [{ question: "Favorite color?", answer: "" }],
      });
      renderWithProviders(
        <AskUserQuestionCard content={doneContent(result, questions)} />,
      );
      expect(screen.getByText(badgeRegex)).toBeInTheDocument();
      expect(screen.getByText(/1\. Favorite color\?/)).toBeInTheDocument();
      expect(screen.getByText(/Unanswered/)).toBeInTheDocument();
    },
  );

  it("shows the error badge when content status is 'error' with non-JSON result", () => {
    const questions = JSON.stringify([{ prompt: "Favorite color?" }]);
    renderWithProviders(
      <AskUserQuestionCard
        content={errorContent(
          "The tool call has been interrupted by the user.",
          questions,
        )}
      />,
    );
    expect(screen.getByText(/Error/)).toBeInTheDocument();
    expect(screen.getByText(/1\. Favorite color\?/)).toBeInTheDocument();
    expect(screen.getByText(/Unanswered/)).toBeInTheDocument();
  });
});

// ── ErrorBoundary (KI-10) ───────────────────────────────────────────

describe("AskUserQuestionCard — ErrorBoundary", () => {
  // Silence the React error log that React emits when an error is caught.
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    consoleError.mockRestore();
  });

  it("renders the fallback card when a render exception is thrown", () => {
    renderWithProviders(
      <AskUserQuestionCard content={null as unknown as ToolCallContent} />,
    );
    expect(
      screen.getByText(/The questionnaire card failed to render/),
    ).toBeInTheDocument();
    // Raw data should also be visible on the fallback card.
    expect(
      screen.getByRole("button", { name: /Copy raw data/ }),
    ).toBeInTheDocument();
  });

  it("resets error state when content identity changes", () => {
    const { rerender } = renderWithProviders(
      <AskUserQuestionCard content={null as unknown as ToolCallContent} />,
    );
    expect(
      screen.getByText(/The questionnaire card failed to render/),
    ).toBeInTheDocument();

    const recovered = doneContent(
      JSON.stringify({ status: "completed", answers: [] }),
      "[]",
    );
    rerender(<AskUserQuestionCard content={recovered} />);

    expect(
      screen.queryByText(/The questionnaire card failed to render/),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Completed/)).toBeInTheDocument();
  });
});

// ── copy behaviour ──────────────────────────────────────────────────

describe("AskUserQuestionCard — copy raw data", () => {
  it("writes raw result to clipboard when copy button is clicked", () => {
    renderWithProviders(
      <AskUserQuestionCard content={doneContent("raw-json-text")} />,
    );
    const copyButton = screen.getByRole("button", { name: /Copy raw data/ });
    fireEvent.click(copyButton);
    expect(mockWriteText).toHaveBeenCalledWith("raw-json-text");
  });
});

// ── form interactions ───────────────────────────────────────────────

describe("AskUserQuestionCard — form interactions", () => {
  it("auto-appends 'Other' when fewer than 4 options are provided", () => {
    const questions = JSON.stringify([
      {
        prompt: "How would you handle it?",
        question_type: "SINGLE_SELECT",
        options: ["By the book", "Efficiency first"],
      },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );

    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);
    // The Other option carries the __OTHER__ sentinel as its value while
    // rendering the localised label as a sibling <label>.
    const otherRadio = radios.find((r) => {
      const wrapper = r.closest("label") ?? r.parentElement;
      return (wrapper?.textContent ?? "").trim() === "Other";
    });
    expect(otherRadio).toBeDefined();
    expect(otherRadio).toHaveAttribute("value", "__OTHER__");
  });

  it("advances through questions and reaches the supplementary step", () => {
    const questions = JSON.stringify([
      { prompt: "Q1?", question_type: "SINGLE_SELECT", options: ["A", "B"] },
      { prompt: "Q2?", question_type: "SINGLE_SELECT", options: ["C", "D"] },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );

    expect(screen.getByText("Q1?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "A" }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));

    expect(screen.getByText("Q2?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "C" }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));

    expect(screen.getByText(/Supplementary/)).toBeInTheDocument();

    // Back from supplementary → last question.
    fireEvent.click(screen.getByRole("button", { name: /Back/ }));
    expect(screen.getByText("Q2?")).toBeInTheDocument();

    // Back from question 2 → question 1.
    fireEvent.click(screen.getByRole("button", { name: /Back/ }));
    expect(screen.getByText("Q1?")).toBeInTheDocument();
  });

  it("disables Next until the current question has a valid answer", () => {
    const questions = JSON.stringify([
      { prompt: "Q1?", question_type: "SINGLE_SELECT", options: ["A", "B"] },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );
    const next = screen.getByRole("button", { name: /Next/ });
    expect(next).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "A" }));
    expect(next).not.toBeDisabled();
  });

  it("disables Back on the first question", () => {
    const questions = JSON.stringify([
      { prompt: "Q1?", question_type: "SINGLE_SELECT", options: ["A"] },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );
    const back = screen.getByRole("button", { name: /Back/ });
    expect(back).toBeDisabled();
  });

  it("reaches the supplementary step after the last question", () => {
    const questions = JSON.stringify([
      { prompt: "Q1?", question_type: "SINGLE_SELECT", options: ["A"] },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );
    fireEvent.click(screen.getByRole("radio", { name: "A" }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(screen.getByText(/Supplementary/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Submit/ })).toBeInTheDocument();
  });

  it("shows an input when 'Other' is selected and forwards its text to the answer", async () => {
    const questions = JSON.stringify([
      { prompt: "Q1?", question_type: "SINGLE_SELECT", options: ["A", "B"] },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );

    fireEvent.click(screen.getByRole("radio", { name: "Other" }));
    const input = screen.getByPlaceholderText(/Please elaborate/);
    expect(input).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "custom reason" } });

    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(screen.getByText(/Supplementary/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Submit/ }));

    await waitFor(() => {
      expect(mockSubmit).toHaveBeenCalledTimes(1);
    });
    const payload = mockSubmit.mock.calls[0][0];
    expect(payload.answers).toHaveLength(1);
    // The custom text overrides the __OTHER__ sentinel.
    expect(payload.answers[0].answer).toBe("custom reason");
  });

  // MULTI_SELECT — the regression this section guards against was a
  // label-vs-sentinel mismatch that left the "Other" checkbox visually
  // unselected even when the user had clicked it.
  it("MULTI_SELECT: ticking 'Other' visually checks the checkbox", () => {
    const questions = JSON.stringify([
      {
        prompt: "Pick any that apply",
        question_type: "MULTI_SELECT",
        options: ["Alpha", "Beta"],
      },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );

    const otherCheckbox = screen.getByRole("checkbox", { name: "Other" });
    expect(otherCheckbox).not.toBeChecked();

    fireEvent.click(otherCheckbox);
    expect(otherCheckbox).toBeChecked();
  });

  it("MULTI_SELECT: keeps regular options checkable alongside 'Other'", () => {
    const questions = JSON.stringify([
      {
        prompt: "Pick any that apply",
        question_type: "MULTI_SELECT",
        options: ["Alpha", "Beta"],
      },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Alpha" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Other" }));

    expect(screen.getByRole("checkbox", { name: "Alpha" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Other" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Beta" })).not.toBeChecked();
  });

  it("MULTI_SELECT: unchecking 'Other' hides the supplementary input", () => {
    const questions = JSON.stringify([
      {
        prompt: "Pick any that apply",
        question_type: "MULTI_SELECT",
        options: ["Alpha"],
      },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );

    const otherCheckbox = screen.getByRole("checkbox", { name: "Other" });
    fireEvent.click(otherCheckbox);
    expect(screen.getByPlaceholderText(/Please elaborate/)).toBeInTheDocument();

    fireEvent.click(otherCheckbox);
    expect(
      screen.queryByPlaceholderText(/Please elaborate/),
    ).not.toBeInTheDocument();
  });
});

// ── submit flow ─────────────────────────────────────────────────────

describe("AskUserQuestionCard — submit flow", () => {
  it("sends the per-question answers plus supplementary input", async () => {
    const questions = JSON.stringify([
      { prompt: "Q1?", question_type: "SINGLE_SELECT", options: ["A"] },
      { prompt: "Q2?", question_type: "SINGLE_SELECT", options: ["B"] },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );

    fireEvent.click(screen.getByRole("radio", { name: "A" }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("radio", { name: "B" }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));

    // Fill supplementary input.
    const supplementary = screen.getByPlaceholderText(/Additional context/);
    fireEvent.change(supplementary, { target: { value: "extra info" } });

    fireEvent.click(screen.getByRole("button", { name: /Submit/ }));

    await waitFor(() => {
      expect(mockSubmit).toHaveBeenCalledTimes(1);
    });
    const payload = mockSubmit.mock.calls[0][0];
    expect(payload.session_id).toBe("test-session");
    expect(payload.answers).toHaveLength(2);
    expect(payload.answers[0]).toMatchObject({
      question_index: 0,
      answer: "A",
      supplementary_input: "extra info",
    });
    expect(payload.answers[1]).toMatchObject({
      question_index: 1,
      answer: "B",
      supplementary_input: "extra info",
    });
  });

  it("warns (not throws) when the backend reports 404 (questionnaire expired)", async () => {
    const { message } = await import("antd");
    const warnSpy = vi.spyOn(message, "warning");
    mockSubmit.mockRejectedValueOnce({ status: 404 });

    const questions = JSON.stringify([
      { prompt: "Q1?", question_type: "SINGLE_SELECT", options: ["A"] },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );

    fireEvent.click(screen.getByRole("radio", { name: "A" }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("button", { name: /Submit/ }));

    await waitFor(() => {
      expect(mockSubmit).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringMatching(/no longer active/),
      );
    });
  });

  it("surfaces a generic error message when submission fails for a non-404 reason", async () => {
    const { message } = await import("antd");
    const errorSpy = vi.spyOn(message, "error");
    mockSubmit.mockRejectedValueOnce(new Error("network down"));

    const questions = JSON.stringify([
      { prompt: "Q1?", question_type: "SINGLE_SELECT", options: ["A"] },
    ]);
    renderWithProviders(
      <AskUserQuestionCard content={callingContent(questions)} isStreaming />,
    );

    fireEvent.click(screen.getByRole("radio", { name: "A" }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("button", { name: /Submit/ }));

    await waitFor(() => {
      expect(mockSubmit).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(errorSpy).toHaveBeenCalledWith(
        expect.stringMatching(/network down/),
      );
    });
  });
});

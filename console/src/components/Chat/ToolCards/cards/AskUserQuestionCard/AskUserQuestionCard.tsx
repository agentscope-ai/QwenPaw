/**
 * AskUserQuestionCard — structured questionnaire tool card.
 *
 * Renders fully custom (no ToolCardShell).  Owns state machine for the
 *   two-step form (per-question + supplementary), parses LLM-supplied
 *   ``questions`` payload defensively, and degrades to a plain-text card
 *   on render or parse failure via a local ErrorBoundary.
 *
 * Layout (single file, top-down):
 *   1. Constants & types
 *   2. helpers (pure functions, no hooks, no state)
 *   3. question-type registry (behavior dispatch — one entry per type)
 *   4. Sub-components (FallbackTextCard, ErrorBoundary)
 *   5. AskUserQuestionCardInner — main interactive component
 *   6. public export (default)
 *
 * i18n:
 *   - All UI strings use ``t("tool.askUserQuestion.<group>.<key>", <EN>)``
 *     with English fallback (project convention — see ApprovalCard).
 *   - The Other option has two roles — internal lookup key (English
 *     sentinel ``__OTHER__``) and visible label
 *     (``t("...options.other")``).  The displayed Radio/Checkbox value
 *     is mapped to/from the sentinel so the persisted answer is
 *     locale-independent.
 */

import React, { useState, useCallback, useMemo, ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { QuestionCircleOutlined } from "@ant-design/icons";
import {
  Button,
  Radio,
  Checkbox,
  Input,
  Space,
  Progress,
  Spin,
  message,
} from "antd";
import type { ToolCallContent } from "../../shared/types";
import { submitQuestionnaireAnswer } from "../../../../../api/modules/questionnaire";
import styles from "./index.module.less";

const { TextArea } = Input;

/**
 * Internal sentinel for the "Other" radio / checkbox value.  This is the
 * form-state lookup key — never user-visible.  The visible label comes
 * from ``t("tool.askUserQuestion.options.other", "Other")``.
 */
const OTHER_OPTION = "__OTHER__";

/** Question kinds supported by the renderer. */
type QuestionType = "SINGLE_SELECT" | "MULTI_SELECT" | "TEXT_INPUT";

/** Single question definition. */
interface Question {
  question_type: QuestionType;
  prompt: string;
  options?: (string | Record<string, unknown>)[];
}

/** Single answer payload submitted to the backend. */
interface Answer {
  question_index: number;
  answer: string;
  supplementary_input?: string;
}

export interface AskUserQuestionCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
  content: ToolCallContent;
  title: string;
}

// ─────────────────────────────────────────────────────────────────
// helpers (pure — no hooks, no React state)
// ─────────────────────────────────────────────────────────────────

/** Coerce an option value to its display string. */
function normalizeOption(opt: unknown): string {
  if (typeof opt === "string") return opt;
  if (opt && typeof opt === "object") {
    const obj = opt as Record<string, unknown>;
    return String(obj.label ?? obj.name ?? obj.value ?? JSON.stringify(obj));
  }
  return String(opt);
}

/** Stringify ``result`` for the plain-text fallback. */
function resultToRawText(result: unknown): string {
  if (result === undefined || result === null) return "";
  return typeof result === "string" ? result : JSON.stringify(result, null, 2);
}

/** Defensively parse ``content.params.questions`` into a ``Question[]``. */
function parseQuestions(content: ToolCallContent): Question[] {
  try {
    const params = content.params as Record<string, unknown>;
    const qs = params?.questions;
    if (Array.isArray(qs)) return qs as Question[];
    if (typeof qs === "string") {
      const parsed = extractJsonArray(qs);
      if (Array.isArray(parsed)) return parsed as Question[];
    }
  } catch (e) {
    console.error("[AskUserQuestionCard] parse questions error:", e);
  }
  return [];
}

/** Extract a JSON array from a possibly-polluted LLM string. */
function extractJsonArray(raw: string): unknown[] | null {
  // 1. Direct parse; if the outer token is a JSON-encoded string, recurse.
  try {
    let parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed;
    if (typeof parsed === "string") {
      parsed = JSON.parse(parsed);
      if (Array.isArray(parsed)) return parsed;
    }
  } catch {
    // continue
  }

  // 2. Strip surrounding quotes (some LLMs wrap the array twice).
  try {
    const unquoted = raw.trim();
    if (unquoted.startsWith('"') && unquoted.endsWith('"')) {
      const inner = JSON.parse(unquoted);
      if (Array.isArray(inner)) return inner;
      if (typeof inner === "string") {
        const parsed = JSON.parse(inner);
        if (Array.isArray(parsed)) return parsed;
      }
    }
  } catch {
    // continue
  }

  // 3. Carve out the first ``[`` … last ``]`` slice.
  try {
    const start = raw.indexOf("[");
    const end = raw.lastIndexOf("]");
    if (start !== -1 && end !== -1 && start < end) {
      const parsed = JSON.parse(raw.slice(start, end + 1));
      if (Array.isArray(parsed)) return parsed;
    }
  } catch {
    // continue
  }

  // 4. Drop markdown code fences and retry.
  try {
    const cleaned = raw.replace(/^```json\s*/i, "").replace(/\s*```$/, "");
    const parsed = JSON.parse(cleaned);
    if (Array.isArray(parsed)) return parsed;
  } catch {
    // give up
  }

  return null;
}

/**
 * Extract plain question text for the parse-failure fallback.  Tries the
 * typed and stringified ``params.questions`` paths so that even partial
 * JSON still renders something useful.
 */
function extractQuestionTexts(
  content: ToolCallContent,
  t: ReturnType<typeof useTranslation>["t"],
): string[] {
  try {
    const params = content.params as Record<string, unknown>;
    const qs = params?.questions;

    let questionsArray: Array<Record<string, unknown>> | null = null;

    if (Array.isArray(qs)) {
      questionsArray = qs as Array<Record<string, unknown>>;
    } else if (typeof qs === "string") {
      const parsed = extractJsonArray(qs);
      if (Array.isArray(parsed)) {
        questionsArray = parsed as Array<Record<string, unknown>>;
      }
    }

    if (questionsArray && questionsArray.length > 0) {
      return questionsArray.map((q, index) => {
        const prompt =
          q.prompt ||
          q.question ||
          q.text ||
          t(
            "tool.askUserQuestion.fallback.questionFallback",
            "Question {{index}}",
            { index: index + 1 },
          );
        return String(prompt);
      });
    }

    return [];
  } catch {
    return [];
  }
}

/** Read the questionnaire status out of an arbitrary ``result`` shape. */
function parseQuestionnaireStatus(result: unknown): string | null {
  try {
    if (result == null) return null;
    const raw = typeof result === "string" ? JSON.parse(result) : result;

    // Direct object/array (test fixtures).
    if (raw && typeof raw === "object") {
      const status = (raw as Record<string, unknown>).status;
      if (typeof status === "string") return status;
    }

    // ToolChunk nesting: {type:"text", text:...} or [{type:"text", text:...}]
    let text: string | undefined;
    if (Array.isArray(raw)) {
      const textBlock = raw.find(
        (item: Record<string, unknown>) => item?.type === "text",
      );
      text = textBlock?.text ? String(textBlock.text) : undefined;
    } else if (raw?.type === "text" && raw?.text) {
      text = String(raw.text);
    }
    if (text) {
      const parsed = JSON.parse(text);
      return (parsed?.status as string) || null;
    }
  } catch {
    return null;
  }
  return null;
}

/** Parse ``params.questions`` for result-rendering fallback. */
function parseResultQuestions(
  content: ToolCallContent,
): Array<Record<string, unknown>> | undefined {
  try {
    const q = content.params?.questions;
    if (typeof q === "string") {
      const parsed = extractJsonArray(q);
      if (Array.isArray(parsed))
        return parsed as Array<Record<string, unknown>>;
    }
    if (Array.isArray(q)) return q as Array<Record<string, unknown>>;
  } catch {
    return undefined;
  }
  return undefined;
}

// ─────────────────────────────────────────────────────────────────
// question-type registry (extensibility seam)
// ─────────────────────────────────────────────────────────────────
//
// Each QuestionType maps to a strategy that owns three behaviors:
//   - isValid:  is the current input sufficient to advance?
//   - buildAnswer: convert current input to the persisted answer string.
//   - render:  the input control(s) for this question type.
//
// Adding a new QuestionType means adding one entry to
// ``QUESTION_TYPE_REGISTRY`` — no other branch in this file needs to
// change.

/**
 * Per-question, per-index user input state captured by the form.
 * Carries the question under inspection + every input map so behavior
 * functions stay pure (no closure over component state).
 */
interface QuestionState {
  question: Question;
  index: number;
  options: string[];
  otherSelected: boolean;
  // Current values for all questions (reused via index lookup).
  answers: Record<number, string>;
  selectedOptions: Record<number, string[]>;
  otherInputs: Record<number, string>;
  // Setters (needed by SINGLE_SELECT / MULTI_SELECT to update state).
  setAnswers: React.Dispatch<React.SetStateAction<Record<number, string>>>;
  setSelectedOptions: React.Dispatch<
    React.SetStateAction<Record<number, string[]>>
  >;
  setOtherInputs: React.Dispatch<React.SetStateAction<Record<number, string>>>;
  // i18n.
  t: ReturnType<typeof useTranslation>["t"];
}

/** Behavior bundle for one QuestionType. */
interface QuestionTypeConfig {
  isValid: (state: QuestionState) => boolean;
  buildAnswer: (state: QuestionState) => string;
  render: (state: QuestionState) => React.ReactNode;
}

/** "Other" supplementary input — shared between selectable types. */
function renderOtherInput(state: QuestionState): React.ReactNode {
  return (
    <TextArea
      rows={2}
      placeholder={state.t(
        "tool.askUserQuestion.options.otherPlaceholder",
        "Please elaborate…",
      )}
      value={state.otherInputs[state.index] || ""}
      onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
        state.setOtherInputs((prev) => ({
          ...prev,
          [state.index]: e.target.value,
        }))
      }
    />
  );
}

const QUESTION_TYPE_REGISTRY: Record<QuestionType, QuestionTypeConfig> = {
  SINGLE_SELECT: {
    isValid: (state) => {
      const answer = state.answers[state.index];
      if (!answer) return false;
      if (answer === OTHER_OPTION) {
        return (state.otherInputs[state.index] || "").trim().length > 0;
      }
      return true;
    },
    buildAnswer: (state) => {
      const a = state.answers[state.index] || "";
      if (a === OTHER_OPTION) {
        // Defensive fallback: ``isValid`` blocks the Next/Submit
        // controls whenever Other is selected but its supplementary
        // input is empty, so the trim() under ``otherInputs`` is
        // expected to be non-empty here.  We still fall back to the
        // ``OTHER_OPTION`` sentinel rather than emitting an empty
        // string, because an empty answer is harder to interpret
        // downstream than the explicit sentinel "user picked Other
        // without specifying".
        return (state.otherInputs[state.index] || "").trim() || OTHER_OPTION;
      }
      return a;
    },
    render: (state) => {
      const otherLabel = state.t("tool.askUserQuestion.options.other", "Other");
      return (
        <>
          <Radio.Group
            className={styles.optionGroup}
            value={state.answers[state.index]}
            onChange={(e) => {
              const value = e.target.value;
              if (value === OTHER_OPTION) {
                state.setAnswers((prev) => ({
                  ...prev,
                  [state.index]: OTHER_OPTION,
                }));
              } else {
                state.setAnswers((prev) => ({
                  ...prev,
                  [state.index]: value,
                }));
                state.setOtherInputs((prev) => ({
                  ...prev,
                  [state.index]: "",
                }));
              }
            }}
          >
            <Space direction="vertical">
              {state.options.map((label) => (
                <Radio
                  key={label}
                  value={label === otherLabel ? OTHER_OPTION : label}
                >
                  {label}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
          {state.otherSelected && (
            <div className={styles.otherInputWrapper}>
              {renderOtherInput(state)}
            </div>
          )}
        </>
      );
    },
  },

  MULTI_SELECT: {
    isValid: (state) => {
      const selected = state.selectedOptions[state.index] || [];
      if (selected.length === 0) return false;
      if (selected.includes(OTHER_OPTION)) {
        return (state.otherInputs[state.index] || "").trim().length > 0;
      }
      return true;
    },
    buildAnswer: (state) => {
      const selected = state.selectedOptions[state.index] || [];
      const otherSelected = selected.includes(OTHER_OPTION);
      const otherText = (state.otherInputs[state.index] || "").trim();
      const parts = selected.filter((opt) => opt !== OTHER_OPTION);
      if (otherSelected) {
        // Same defensive fallback as SINGLE_SELECT: ``isValid``
        // guarantees a non-empty supplementary input when
        // ``OTHER_OPTION`` is among the selections, so ``otherText``
        // should be non-empty here.
        parts.push(otherText || OTHER_OPTION);
      }
      return parts.join(", ");
    },
    render: (state) => {
      const otherLabel = state.t("tool.askUserQuestion.options.other", "Other");
      // The checkbox group matches ``value`` (label or sentinel) against
      // each ``<Checkbox value>`` by string equality.  Store and drive
      // both sides with the same sentinel / label so the visual
      // selection tracks state on every render — see git history for
      // the prior mismatch bug where ``Checkbox.value="__OTHER__"`` did
      // not match ``displaySelected=["Other"]``.
      const rawSelected = state.selectedOptions[state.index] || [];
      const checkboxValues = state.options.map((label) =>
        label === otherLabel ? OTHER_OPTION : label,
      );
      const handleChange = (values: Array<string | number | boolean>) => {
        state.setSelectedOptions((prev) => ({
          ...prev,
          [state.index]: values.map((v) => String(v)),
        }));
      };
      return (
        <>
          <Checkbox.Group
            className={styles.optionGroup}
            value={rawSelected}
            onChange={handleChange}
          >
            <Space direction="vertical">
              {checkboxValues.map((value, i) => {
                const label = state.options[i];
                return (
                  <Checkbox key={value} value={value}>
                    {label}
                  </Checkbox>
                );
              })}
            </Space>
          </Checkbox.Group>
          {state.otherSelected && (
            <div className={styles.otherInputWrapper}>
              {renderOtherInput(state)}
            </div>
          )}
        </>
      );
    },
  },

  TEXT_INPUT: {
    isValid: (state) => (state.answers[state.index] || "").length > 0,
    buildAnswer: (state) => state.answers[state.index] || "",
    render: (state) => (
      <TextArea
        rows={3}
        placeholder={state.t(
          "tool.askUserQuestion.options.enterAnswer",
          "Please enter your answer…",
        )}
        value={state.answers[state.index] || ""}
        onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
          state.setAnswers((prev) => ({
            ...prev,
            [state.index]: e.target.value,
          }))
        }
      />
    ),
  },
};

// ─────────────────────────────────────────────────────────────────
// sub-components
// ─────────────────────────────────────────────────────────────────

/** Plain-text card shown when the structured render or parse failed. */
const FallbackTextCard: React.FC<{ title: string; rawText: string }> = ({
  title,
  rawText,
}) => {
  const { t } = useTranslation();
  return (
    <div className={styles.fallbackCard}>
      <div className={styles.fallbackTitle}>{title}</div>
      <pre className={styles.fallbackContent}>{rawText}</pre>
      <button
        type="button"
        aria-label={t("tool.askUserQuestion.fallback.copyRaw", "Copy raw data")}
        onClick={() => {
          navigator.clipboard
            .writeText(rawText)
            .then(() =>
              message.success(
                t("tool.askUserQuestion.fallback.copied", "Copied"),
              ),
            )
            .catch(() =>
              message.error(
                t("tool.askUserQuestion.fallback.copyFailed", "Copy failed"),
              ),
            );
        }}
        className={styles.fallbackCopy}
      >
        {t("tool.askUserQuestion.fallback.copyRaw", "Copy raw data")}
      </button>
    </div>
  );
};

/**
 * Local ErrorBoundary so a render crash in the questionnaire logic
 * cannot poison the chat scroll.  Resets on a fresh ``content``.
 */
class AskUserQuestionErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error("[AskUserQuestionCard] render error:", error, errorInfo);
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps): void {
    if (prevProps.content !== this.props.content && this.state.hasError) {
      this.setState({ hasError: false });
    }
  }

  render() {
    if (this.state.hasError) {
      const rawText = resultToRawText(this.props.content);
      return <FallbackTextCard title={this.props.title} rawText={rawText} />;
    }
    return this.props.children;
  }
}

// ─────────────────────────────────────────────────────────────────
// parse-failure fallback renderer
// ─────────────────────────────────────────────────────────────────

/** Question-list fallback when ``questions`` failed to parse. */
function renderParseFailureFallback(
  content: ToolCallContent,
  isError: boolean,
  questionTexts: string[],
  t: ReturnType<typeof useTranslation>["t"],
) {
  if (!isError) {
    return (
      <div className={styles.noQuestions}>
        {t(
          "tool.askUserQuestion.fallback.noQuestions",
          "Could not parse the question data",
        )}
      </div>
    );
  }

  if (questionTexts.length > 0) {
    return (
      <div className={styles.fallbackTextWrapper}>
        <div className={styles.fallbackTitle}>
          {t(
            "tool.askUserQuestion.fallback.questionParseFailedHint",
            "Could not parse the question data; here are the questions to answer in chat:",
          )}
        </div>
        <div className={styles.fallbackQuestionList}>
          {questionTexts.map((text, index) => (
            <div key={index} className={styles.fallbackQuestionItem}>
              <span className={styles.fallbackQuestionIndex}>{index + 1}.</span>
              <span className={styles.fallbackQuestionText}>{text}</span>
            </div>
          ))}
        </div>
        <div className={styles.fallbackHint}>
          {t(
            "tool.askUserQuestion.fallback.hint",
            "Please type your answer directly in chat",
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.noQuestions}>
      <div style={{ marginBottom: 8 }}>
        {t(
          "tool.askUserQuestion.fallback.questionParseFailed",
          "Could not parse the question data",
        )}
      </div>
      <div style={{ fontSize: 12, color: "#666" }}>
        {content.result
          ? t(
              "tool.askUserQuestion.fallback.errorDetail",
              "Error detail: {{error}}",
              { error: resultToRawText(content.result) },
            )
          : t(
              "tool.askUserQuestion.fallback.noErrorDetail",
              "No detailed error information provided",
            )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// main component
// ─────────────────────────────────────────────────────────────────

/** Interactive form + result renderer. */
const AskUserQuestionCardInner: React.FC<AskUserQuestionCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const title = t("tool.askUserQuestion.title", "Ask");
  // Memo: avoid reparsing on every render.
  const questions = useMemo(() => parseQuestions(content), [content]);

  const [currentStep, setCurrentStep] = useState<"question" | "supplementary">(
    "question",
  );
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [selectedOptions, setSelectedOptions] = useState<
    Record<number, string[]>
  >({});
  const [otherInputs, setOtherInputs] = useState<Record<number, string>>({});
  const [supplementaryInput, setSupplementaryInput] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const isError = content.status === "error";
  const isDone = content.status === "done";
  const isLoading = content.status === "calling" && isStreaming;
  const hasOutput = isDone && content.result !== undefined;

  const currentQuestion = questions[currentQuestionIndex];
  const totalQuestions = questions.length;
  const progress =
    totalQuestions > 0
      ? Math.round(((currentQuestionIndex + 1) / totalQuestions) * 100)
      : 0;

  // Localised Other label — drives both visible text and option-dedup.
  const otherLabel = useMemo(
    () => t("tool.askUserQuestion.options.other", "Other"),
    [t],
  );

  // Current-question option list (always ends with Other).
  const normalizedOptions = useMemo(() => {
    if (!currentQuestion) return [];
    const raw = (currentQuestion.options || []).map((opt) =>
      normalizeOption(opt),
    );
    const withoutOther = raw.filter((label) => label.trim() !== otherLabel);
    return [...withoutOther, otherLabel];
  }, [currentQuestion, otherLabel]);

  // Whether the user picked "Other" on the current question.  The
  // displayed options carry the localised label; the stored answer /
  // selection carry the ``OTHER_OPTION`` sentinel.
  const isOtherSelected = useMemo(() => {
    if (!currentQuestion) return false;
    if (currentQuestion.question_type === "SINGLE_SELECT") {
      return answers[currentQuestionIndex] === OTHER_OPTION;
    }
    if (currentQuestion.question_type === "MULTI_SELECT") {
      return (selectedOptions[currentQuestionIndex] || []).includes(
        OTHER_OPTION,
      );
    }
    return false;
  }, [currentQuestion, currentQuestionIndex, answers, selectedOptions]);

  // Compose the QuestionState bundle passed to registry behaviors.
  const questionState: QuestionState | null = useMemo(() => {
    if (!currentQuestion) return null;
    return {
      question: currentQuestion,
      index: currentQuestionIndex,
      options: normalizedOptions,
      otherSelected: isOtherSelected,
      answers,
      selectedOptions,
      otherInputs,
      setAnswers,
      setSelectedOptions,
      setOtherInputs,
      t,
    };
  }, [
    currentQuestion,
    currentQuestionIndex,
    normalizedOptions,
    isOtherSelected,
    answers,
    selectedOptions,
    otherInputs,
    t,
  ]);

  // Whether the current question's user input is valid for advancing.
  const canGoNext = useMemo(() => {
    if (!questionState) return false;
    // Unknown / missing ``question_type`` falls back to the TEXT_INPUT
    // validator (anything-non-empty) so render-time lenient behaviour
    // matches the pre-registry implementation.
    const cfg =
      QUESTION_TYPE_REGISTRY[currentQuestion!.question_type] ??
      QUESTION_TYPE_REGISTRY.TEXT_INPUT;
    return cfg.isValid(questionState);
  }, [questionState, currentQuestion]);

  const handleNext = useCallback(() => {
    if (!canGoNext) return;
    if (currentQuestionIndex < totalQuestions - 1) {
      setCurrentQuestionIndex((prev) => prev + 1);
    } else {
      setCurrentStep("supplementary");
    }
  }, [canGoNext, currentQuestionIndex, totalQuestions]);

  const handleBack = useCallback(() => {
    if (currentStep === "supplementary") {
      setCurrentStep("question");
      return;
    }
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex((prev) => prev - 1);
    }
  }, [currentStep, currentQuestionIndex]);

  const handleSubmit = useCallback(async () => {
    // Build per-question answers via the registry — no manual type checks.
    const allAnswers: Answer[] = questions.map((q, idx) => {
      const cfg =
        QUESTION_TYPE_REGISTRY[q.question_type] ??
        QUESTION_TYPE_REGISTRY.TEXT_INPUT;
      const perQuestion = {
        question: q,
        index: idx,
        options: idx === currentQuestionIndex ? normalizedOptions : [],
        otherSelected: idx === currentQuestionIndex ? isOtherSelected : false,
        answers,
        selectedOptions,
        otherInputs,
        setAnswers,
        setSelectedOptions,
        setOtherInputs,
        t,
      };
      return {
        question_index: idx,
        answer: cfg.buildAnswer(perQuestion),
        supplementary_input: supplementaryInput,
      };
    });

    const sessionId =
      (typeof window !== "undefined" &&
        (window as unknown as { currentSessionId?: string })
          .currentSessionId) ||
      "";
    if (!sessionId) {
      message.error(
        t(
          "tool.askUserQuestion.messages.noSession",
          "Cannot identify the current session. Please refresh and retry.",
        ),
      );
      return;
    }

    setSubmitting(true);
    try {
      await submitQuestionnaireAnswer({
        session_id: sessionId,
        answers: allAnswers,
      });
    } catch (err) {
      const status =
        (err as { status?: number; statusCode?: number })?.status ??
        (err as { statusCode?: number })?.statusCode;
      if (status === 404) {
        message.warning(
          t(
            "tool.askUserQuestion.messages.questionnaireExpired",
            "This questionnaire is no longer active (timed out or cancelled). Please wait for the agent to re-issue it.",
          ),
        );
      } else {
        message.error(
          t(
            "tool.askUserQuestion.messages.submitFailed",
            "Submit failed: {{message}}",
            { message: ((err as Error)?.message || String(err)) as string },
          ),
        );
      }
    } finally {
      setSubmitting(false);
    }
  }, [
    questions,
    currentQuestionIndex,
    normalizedOptions,
    isOtherSelected,
    answers,
    selectedOptions,
    otherInputs,
    supplementaryInput,
    t,
  ]);

  /**
   * Result list (completed / timeout / cancelled / interrupted).
   *  - Uses result.answers when present and parseable.
   *  - Falls back to rawQuestions with null answers when result.answers is
   *    empty (timeout / cancel / interrupt), so the question list still
   *    shows "Unanswered" markers.
   */
  const renderResult = () => {
    if (content.result == null) return null;

    const rawQuestions = parseResultQuestions(content);

    // Parse ``result`` into a plain object; several shapes are supported.
    let parsed: Record<string, unknown> | null = null;
    try {
      const raw =
        typeof content.result === "string"
          ? JSON.parse(content.result)
          : content.result;
      if (Array.isArray(raw)) {
        const textBlock = raw.find(
          (item: Record<string, unknown>) => item?.type === "text",
        );
        if (textBlock?.text) {
          parsed = JSON.parse(String(textBlock.text));
        }
      } else if (raw?.type === "text" && raw?.text) {
        parsed = JSON.parse(String(raw.text));
      } else if (raw && typeof raw === "object") {
        parsed = raw as Record<string, unknown>;
      }
    } catch {
      parsed = null;
    }

    const resultAnswers: Array<Record<string, unknown>> | undefined =
      parsed?.answers && Array.isArray(parsed.answers)
        ? (parsed.answers as Array<Record<string, unknown>>)
        : undefined;

    // Nothing to show — degrade to raw text.
    if (!resultAnswers && (!rawQuestions || rawQuestions.length === 0)) {
      return (
        <FallbackTextCard
          title={t(
            "tool.askUserQuestion.fallback.resultParseFailed",
            "The questionnaire result could not be parsed. Showing raw data instead.",
          )}
          rawText={resultToRawText(content.result)}
        />
      );
    }

    const displayAnswers =
      resultAnswers && resultAnswers.length > 0
        ? resultAnswers
        : (rawQuestions || []).map((q) => ({
            question: q.prompt as string | undefined,
            answer: null,
          }));

    return (
      <div className={styles.resultList}>
        {displayAnswers.map((answerObj, idx) => {
          const questionObj = rawQuestions?.[idx];
          const answerVal = (answerObj?.answer as string | null) ?? null;
          const promptText =
            (answerObj?.question as string) ||
            (questionObj?.prompt as string) ||
            t("tool.askUserQuestion.fallback.questionFallback", "Q{{index}}", {
              index: idx + 1,
            });
          const isUnanswered = answerVal == null || answerVal === "";

          return (
            <div key={idx} className={styles.resultItem}>
              <div className={styles.resultQuestion}>{`${
                idx + 1
              }. ${promptText}`}</div>
              <div
                className={[
                  styles.resultAnswer,
                  isUnanswered ? styles.resultAnswerUnanswered : "",
                ].join(" ")}
              >
                {isUnanswered
                  ? t("tool.askUserQuestion.fallback.unanswered", "Unanswered")
                  : answerVal}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  // Per-type input control, dispatched via the registry — no in-line switch.
  const renderQuestionControl = () => {
    if (!questionState || !currentQuestion) return null;
    const cfg =
      QUESTION_TYPE_REGISTRY[currentQuestion.question_type] ??
      QUESTION_TYPE_REGISTRY.TEXT_INPUT;
    return cfg.render(questionState);
  };

  // Main form renderer (questions-step or supplementary-step).
  const renderForm = () => {
    if (questions.length === 0) {
      return renderParseFailureFallback(
        content,
        isError,
        extractQuestionTexts(content, t),
        t,
      );
    }

    return (
      <div className={styles.formWrapper}>
        <div className={styles.formProgress}>
          <Progress
            percent={progress}
            size="small"
            format={() => `${currentQuestionIndex + 1}/${totalQuestions}`}
          />
        </div>

        {currentStep === "question" ? (
          <>
            <div className={styles.questionTitle}>
              {currentQuestion?.prompt}
            </div>
            {renderQuestionControl()}
            <div className={styles.formActions}>
              <Space>
                <Button
                  size="small"
                  onClick={handleBack}
                  disabled={currentQuestionIndex === 0}
                >
                  {t("tool.askUserQuestion.actions.back", "Back")}
                </Button>
                <Button
                  type="primary"
                  size="small"
                  onClick={handleNext}
                  disabled={submitting || !canGoNext}
                >
                  {t("tool.askUserQuestion.actions.next", "Next")}
                </Button>
              </Space>
            </div>
          </>
        ) : (
          <>
            <div className={styles.supplementaryHint}>
              {t(
                "tool.askUserQuestion.options.supplementaryHint",
                "Supplementary (optional)",
              )}
            </div>
            <TextArea
              rows={2}
              placeholder={t(
                "tool.askUserQuestion.options.supplementaryPlaceholder",
                "Additional context for the chosen answers…",
              )}
              value={supplementaryInput}
              onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
                setSupplementaryInput(e.target.value)
              }
            />
            <div className={styles.formActions}>
              <Space>
                <Button size="small" onClick={handleBack}>
                  {t("tool.askUserQuestion.actions.back", "Back")}
                </Button>
                <Button
                  type="primary"
                  size="small"
                  loading={submitting}
                  disabled={submitting}
                  onClick={handleSubmit}
                >
                  {t("tool.askUserQuestion.actions.submit", "Submit")}
                </Button>
              </Space>
            </div>
          </>
        )}
      </div>
    );
  };

  // Status badge (header right).
  const getStatusInfo = () => {
    if (isError) {
      return {
        text: t("tool.askUserQuestion.status.error", "Error"),
        className: styles.statusError,
      };
    }
    if (isDone) {
      const status = parseQuestionnaireStatus(content.result);
      if (status === "timeout") {
        return {
          text: t("tool.askUserQuestion.status.timeout", "Timed out"),
          className: styles.statusWarning,
        };
      }
      if (status === "cancelled") {
        return {
          text: t("tool.askUserQuestion.status.cancelled", "Cancelled"),
          className: styles.statusCancelled,
        };
      }
      if (status === "interrupted") {
        return {
          text: t("tool.askUserQuestion.status.interrupted", "Interrupted"),
          className: styles.statusInterrupted,
        };
      }
      return {
        text: t("tool.askUserQuestion.status.completed", "Completed"),
        className: styles.statusSuccess,
      };
    }
    if (isLoading) {
      return {
        text: t("tool.askUserQuestion.status.loading", "Waiting for answer…"),
        className: styles.statusDefault,
      };
    }
    return {
      text: t("tool.askUserQuestion.status.pending", "Pending"),
      className: styles.statusDefault,
    };
  };

  const statusInfo = getStatusInfo();
  const cardClassName = isError
    ? `${styles.questionnaireCard} ${styles.questionnaireCardError}`
    : styles.questionnaireCard;

  return (
    <div className={cardClassName}>
      <div className={styles.header}>
        {isLoading ? (
          <Spin size="small" />
        ) : (
          <QuestionCircleOutlined
            className={[
              styles.icon,
              isError ? styles.iconError : styles.iconPrimary,
            ].join(" ")}
          />
        )}
        <span className={styles.title}>{title}</span>
        <span className={[styles.statusBadge, statusInfo.className].join(" ")}>
          {statusInfo.text}
        </span>
      </div>
      <div className={styles.body}>
        {hasOutput || isError ? renderResult() : renderForm()}
      </div>
    </div>
  );
};

/**
 * Public export: wraps ``Inner`` in a local ErrorBoundary so a render
 * crash degrades to raw text rather than poisoning the chat scroll.
 */
const AskUserQuestionCard: React.FC<AskUserQuestionCardProps> = (props) => {
  const { t } = useTranslation();
  return (
    <AskUserQuestionErrorBoundary
      content={props.content}
      title={t(
        "tool.askUserQuestion.fallback.renderFailed",
        "The questionnaire card failed to render. Showing raw data instead.",
      )}
    >
      <AskUserQuestionCardInner {...props} />
    </AskUserQuestionErrorBoundary>
  );
};

export { AskUserQuestionCard };

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button, Input } from "antd";
import { ChevronDown, ChevronUp, Circle, Dot, Send } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  userInputApi,
  type UserInputQuestion,
  type UserInputRequest,
} from "../../api/modules/userInput";
import styles from "./index.module.less";

interface UserInputPanelProps {
  request: UserInputRequest;
  onResolved?: () => void;
}

type AnswerValue = {
  selected?: string;
  custom?: string;
};

function firstDefault(question: UserInputQuestion): AnswerValue {
  const recommended = question.options.find((item) => item.recommended);
  const selected = question.default_value || recommended?.value || "";
  return { selected };
}

function buildQuestionKey(request: UserInputRequest): string {
  const questionIds = request.questions.map((item) => item.id).join("|");
  return `${request.request_id}:${request.question_index}:${questionIds}`;
}

function isAnswered(question: UserInputQuestion, value: AnswerValue): boolean {
  if (!question.required) return true;
  if (question.kind === "free_text") return Boolean(value.custom?.trim());
  if (question.kind === "single_choice") return Boolean(value.selected);
  if (value.selected === "__custom__") return Boolean(value.custom?.trim());
  return Boolean(value.selected);
}

const UserInputPanel: React.FC<UserInputPanelProps> = ({
  request,
  onResolved,
}) => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>(() => {
    const initial: Record<string, AnswerValue> = {};
    request.questions.forEach((question) => {
      initial[question.id] = firstDefault(question);
    });
    return initial;
  });
  const questionKey = useMemo(() => buildQuestionKey(request), [request]);
  const lastQuestionKeyRef = useRef(questionKey);

  useEffect(() => {
    if (lastQuestionKeyRef.current === questionKey) return;
    lastQuestionKeyRef.current = questionKey;

    setAnswers((prev) => {
      const next: Record<string, AnswerValue> = {};
      request.questions.forEach((item) => {
        next[item.id] = prev[item.id] || firstDefault(item);
      });
      return next;
    });
    setExpanded(true);
  }, [questionKey, request.questions]);

  const question = request.questions[0];
  const total = request.total_questions || request.questions.length || 1;
  const currentNumber = (request.question_index ?? 0) + 1;
  const currentAnswered = isAnswered(question, answers[question.id] || {});

  const selected = answers[question.id]?.selected || "";
  const custom = answers[question.id]?.custom || "";

  const setSelected = (value: string) => {
    setAnswers((prev) => ({
      ...prev,
      [question.id]: {
        ...(prev[question.id] || {}),
        selected: value,
      },
    }));
  };

  const setCustom = (value: string) => {
    setAnswers((prev) => ({
      ...prev,
      [question.id]: {
        ...(prev[question.id] || {}),
        custom: value,
        selected:
          question.kind === "free_text"
            ? "__custom__"
            : prev[question.id]?.selected,
      },
    }));
  };

  const buildPayloadAnswers = () => {
    const payload: Record<string, unknown> = {};
    request.questions.forEach((item) => {
      const value = answers[item.id] || {};
      if (item.kind === "free_text" || value.selected === "__custom__") {
        payload[item.id] = value.custom?.trim() || "";
      } else {
        payload[item.id] = value.selected || "";
      }
    });
    return payload;
  };

  const submit = async (
    action: "submit" | "ignore" | "cancel",
  ) => {
    setSubmitting(true);
    try {
      await userInputApi.answer(request.request_id, {
        action,
        answers: action === "submit" ? buildPayloadAnswers() : {},
      });
      onResolved?.();
    } finally {
      setSubmitting(false);
    }
  };

  const confirmCurrent = async () => {
    if (!currentAnswered) return;
    await submit("submit");
  };

  return (
    <section className={styles.panel} data-testid="user-input-panel">
      <div className={styles.header}>
        <div className={styles.heading}>
          <span className={styles.title}>
            {request.title || t("userInput.title", "Need confirmation")}
          </span>
          <span className={styles.counter}>
            {t("userInput.questionCounter", "Question")} {currentNumber}/
            {total}
          </span>
        </div>
        <Button
          type="text"
          size="small"
          className={styles.iconButton}
          onClick={() => setExpanded((value) => !value)}
          icon={expanded ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        >
          {expanded
            ? t("common.collapse", "Collapse")
            : t("common.expand", "Expand")}
        </Button>
      </div>

      {expanded && (
        <>
          <div className={styles.progressTrack}>
            <span
              className={styles.progressFill}
              style={{ width: `${(currentNumber / total) * 100}%` }}
            />
          </div>
          <div className={styles.question}>{question.question}</div>

          {question.kind !== "free_text" && (
            <div className={styles.options}>
              {question.options.map((option) => {
                const active = selected === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    className={`${styles.option} ${
                      active ? styles.optionActive : ""
                    }`}
                    onClick={() => setSelected(option.value)}
                  >
                    <span className={styles.radio}>
                      {active ? <Dot size={20} /> : <Circle size={14} />}
                    </span>
                    <span className={styles.optionBody}>
                      <span className={styles.optionTitle}>
                        {option.label}
                        {option.recommended && (
                          <span className={styles.recommended}>
                            {t("userInput.recommended", "Recommended")}
                          </span>
                        )}
                      </span>
                      {option.description && (
                        <span className={styles.optionDescription}>
                          {option.description}
                        </span>
                      )}
                    </span>
                  </button>
                );
              })}
              {question.kind === "choice_with_custom" && (
                <button
                  type="button"
                  className={`${styles.option} ${
                    selected === "__custom__" ? styles.optionActive : ""
                  }`}
                  onClick={() => setSelected("__custom__")}
                >
                  <span className={styles.radio}>
                    {selected === "__custom__" ? (
                      <Dot size={20} />
                    ) : (
                      <Circle size={14} />
                    )}
                  </span>
                  <span className={styles.optionBody}>
                    <span className={styles.optionTitle}>
                      {t("userInput.customAnswer", "Custom answer")}
                    </span>
                    <span className={styles.optionDescription}>
                      {question.placeholder ||
                        t("userInput.customHint", "Enter your own answer")}
                    </span>
                  </span>
                </button>
              )}
            </div>
          )}

          {(question.kind === "free_text" || selected === "__custom__") && (
            <Input.TextArea
              className={styles.textarea}
              value={custom}
              onChange={(event) => setCustom(event.target.value)}
              placeholder={
                question.placeholder ||
                t("userInput.inputPlaceholder", "Enter your answer...")
              }
              autoSize={{ minRows: 2, maxRows: 4 }}
            />
          )}

          <div className={styles.footer}>
            <div className={styles.meta}>
              {t(
                "userInput.stepHint",
                "Confirm this answer to continue to the next question.",
              )}
            </div>
            <div className={styles.actions}>
              <Button
                size="small"
                type="text"
                disabled={submitting}
                onClick={() => submit("ignore")}
              >
                {t("userInput.ignore", "Ignore")}
              </Button>
              <Button
                size="small"
                type="primary"
                icon={<Send size={14} />}
                loading={submitting}
                disabled={!currentAnswered}
                onClick={confirmCurrent}
              >
                {t("common.submit", "Submit")}
              </Button>
            </div>
          </div>
        </>
      )}
    </section>
  );
};

export default UserInputPanel;

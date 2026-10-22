import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  decidePawAppTask,
  type ApprovalRequest,
  type ApprovalDecision,
  type ApprovalReceipt,
} from "../../../../api/modules/pawappTasks";
import { createClientMessageId } from "../../../../utils/clientMessageId";
import styles from "./PawAppTaskCard.module.less";

/** An explicit user gesture authorizes one immutable proposal, never a setting. */
export default function TaskApprovalForm({
  appId,
  workspaceId,
  taskId,
  request,
  receipt,
  onSettled,
}: {
  appId: string;
  workspaceId: string;
  taskId: string;
  request: ApprovalRequest;
  receipt?: ApprovalReceipt | null;
  onSettled: () => void;
}) {
  const { t } = useTranslation();
  const [comment, setComment] = useState("");
  const [state, setState] = useState<
    "idle" | "sending" | "accepted" | "failed" | "rejected"
  >("idle");
  const [expired, setExpired] = useState(false);
  const intent = useRef<{
    commandId: string;
    decision: ApprovalDecision;
  } | null>(null);
  useEffect(() => {
    if (!receipt) return;
    intent.current = {
      commandId: receipt.command_id,
      decision: receipt.decision,
    };
    setComment(receipt.decision.comment ?? "");
    setState(
      receipt.state === "accepted"
        ? "accepted"
        : receipt.state === "rejected"
        ? "rejected"
        : receipt.state === "unknown"
        ? "failed"
        : "sending",
    );
  }, [receipt]);
  useEffect(() => {
    if (request.expires_at == null) return;
    let timer: ReturnType<typeof setTimeout>;
    const check = () => {
      const remaining = request.expires_at! * 1000 - Date.now();
      if (remaining <= 0) {
        setExpired(true);
        return;
      }
      timer = setTimeout(check, Math.min(remaining, 2147483647));
    };
    check();
    return () => clearTimeout(timer);
  }, [request.expires_at]);
  const submit = async (decisionId: ApprovalDecision["decision_id"]) => {
    if (state === "sending" || state === "accepted") return;
    if (!intent.current) {
      const choice = request.choices.find(
        (item) => item.decision_id === decisionId,
      );
      if (expired || !choice || (choice.requires_comment && !comment.trim()))
        return;
      intent.current = {
        commandId: createClientMessageId(),
        decision: {
          request_id: request.request_id,
          subject_digest: request.subject_digest,
          decision_id: decisionId,
          comment: comment.trim() || null,
        },
      };
    }
    setState("sending");
    try {
      const result = await decidePawAppTask(
        appId,
        workspaceId,
        taskId,
        intent.current.commandId,
        intent.current.decision,
      );
      setState(
        result.state === "accepted"
          ? "accepted"
          : result.state === "rejected"
          ? "rejected"
          : "failed",
      );
    } catch {
      setState("failed");
    } finally {
      onSettled();
    }
  };
  return (
    <section className={styles.inputRequest} aria-label={request.title}>
      <strong>{request.title}</strong>
      <p>{request.summary}</p>
      {!!request.effects?.length && (
        <ul>
          {request.effects.map((effect) => (
            <li key={effect}>{effect}</li>
          ))}
        </ul>
      )}
      {request.cost && (
        <p>
          {request.cost.amount != null &&
            `${request.cost.amount} ${request.cost.currency} · `}
          {request.cost.description}
        </p>
      )}
      {request.choices.some((choice) => choice.requires_comment) && (
        <label className={styles.customAnswer}>
          {t("tool.pawappTask.approvalComment", {
            choices: request.choices
              .filter((choice) => choice.requires_comment)
              .map((choice) => choice.label)
              .join(", "),
          })}
          <textarea
            value={comment}
            maxLength={2000}
            disabled={intent.current !== null}
            onChange={(event) => setComment(event.target.value)}
          />
        </label>
      )}
      <div className={styles.answerOptions}>
        {request.choices.map((choice) => (
          <button
            type="button"
            key={choice.decision_id}
            title={choice.description}
            disabled={
              expired ||
              intent.current !== null ||
              (choice.requires_comment && !comment.trim())
            }
            onClick={() => void submit(choice.decision_id)}
          >
            {choice.label}
          </button>
        ))}
      </div>
      {state === "failed" && (
        <button
          type="button"
          onClick={() => void submit(intent.current!.decision.decision_id)}
        >
          {t("tool.pawappTask.approvalRetry")}
        </button>
      )}
      {expired && state === "idle" && (
        <p role="alert">{t("tool.pawappTask.approvalExpired")}</p>
      )}
      {state === "accepted" && (
        <p role="status">{t("tool.pawappTask.approvalAccepted")}</p>
      )}
      {(state === "failed" || state === "rejected") && (
        <p role="alert">
          {t(
            state === "failed"
              ? "tool.pawappTask.approvalFailed"
              : "tool.pawappTask.approvalRejected",
          )}
        </p>
      )}
    </section>
  );
}

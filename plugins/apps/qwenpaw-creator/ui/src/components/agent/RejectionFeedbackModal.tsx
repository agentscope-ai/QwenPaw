import { useEffect, useRef, useState } from "react";
import { Input, Modal } from "antd";
import type {
  FileProjectReviewRejectionAction,
  FileProjectReviewRejectionFeedback,
} from "@/contracts/creator";

export default function RejectionFeedbackModal({
  open,
  busy,
  targetCount,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  busy: boolean;
  targetCount: number;
  onCancel: () => void;
  onSubmit: (feedback: FileProjectReviewRejectionFeedback) => void;
}) {
  const [feedbackNote, setFeedbackNote] = useState("");
  const [pendingAction, setPendingAction] =
    useState<FileProjectReviewRejectionAction | null>(null);
  const submitLock = useRef(false);
  const wasBusy = useRef(false);

  useEffect(() => {
    if (!open) return;
    setFeedbackNote("");
    setPendingAction(null);
    submitLock.current = false;
    wasBusy.current = false;
  }, [open]);

  useEffect(() => {
    if (busy) {
      wasBusy.current = true;
      return;
    }
    if (!wasBusy.current) return;
    wasBusy.current = false;
    submitLock.current = false;
    setPendingAction(null);
  }, [busy]);

  const submit = (action: FileProjectReviewRejectionAction) => {
    if (busy || submitLock.current) return;
    submitLock.current = true;
    setPendingAction(action);
    const normalizedFeedback = feedbackNote.trim();
    onSubmit({
      action,
      ...(normalizedFeedback ? { feedbackNote: normalizedFeedback } : {}),
    });
  };
  const submitting = busy || pendingAction !== null;

  return (
    <Modal
      title={
        <div className="min-w-0 pr-10">
          <div className="text-base font-semibold leading-6 text-[var(--color-text-primary)]">
            撤销内容
          </div>
          <div className="mt-0.5 text-xs font-normal leading-5 text-[var(--color-text-tertiary)]">
            将撤销 {targetCount} 项内容
          </div>
        </div>
      }
      open={open}
      onCancel={submitting ? undefined : onCancel}
      closable={!submitting}
      maskClosable={!submitting}
      keyboard={!submitting}
      destroyOnHidden
      width={520}
      footer={null}
    >
      <div className="pt-1">
        <label className="block text-sm text-[var(--color-text-primary)]">
          <span className="block font-medium leading-5">
            反馈与调整要求
            <span className="ml-1 font-normal text-[var(--color-text-tertiary)]">
              可选
            </span>
          </span>
          <span
            id="rejection-feedback-help"
            className="mb-2 mt-1 block text-xs leading-5 text-[var(--color-text-tertiary)]"
          >
            可以同时说明哪里不对，以及希望如何调整。
          </span>
          <Input.TextArea
            aria-label="反馈与调整要求"
            aria-describedby="rejection-feedback-help"
            value={feedbackNote}
            maxLength={2000}
            showCount
            autoFocus
            autoSize={{ minRows: 4, maxRows: 8 }}
            onChange={(event) => setFeedbackNote(event.target.value)}
            placeholder="例如：人物仍像巅峰时期；请保持同一角色身份，改为衣衫褴褛、面容憔悴。"
          />
        </label>

        <div className="mt-5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2 text-xs leading-5 text-[var(--color-text-secondary)]">
          <span className="font-medium text-[var(--color-text-primary)]">
            仅撤销
          </span>
          不会唤醒 Agent；
          <span className="ml-1 font-medium text-[var(--color-text-primary)]">
            撤销并重做
          </span>
          会把以上反馈作为强制约束继续执行。
        </div>

        <div className="mt-5 flex flex-col-reverse gap-2 border-t border-[var(--color-border)] pt-4 sm:flex-row sm:flex-wrap sm:justify-end">
          <button
            type="button"
            disabled={submitting}
            onClick={onCancel}
            className="min-h-10 w-full rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-secondary)] disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
          >
            取消
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={() => submit("UNDO_ONLY")}
            className="min-h-10 w-full rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-text-tertiary)] hover:bg-[var(--color-bg-secondary)] disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
          >
            {submitting && pendingAction === "UNDO_ONLY"
              ? "正在撤销…"
              : "仅撤销"}
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={() => submit("UNDO_AND_REGENERATE")}
            className="min-h-10 w-full rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
          >
            {submitting && pendingAction === "UNDO_AND_REGENERATE"
              ? "正在提交…"
              : "撤销并重做"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

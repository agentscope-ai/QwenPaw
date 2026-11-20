import { useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Popover } from "antd";
import { LoaderCircle, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./DeleteAction.module.less";

/** Inline confirmation that closes only after the operation resolves. */
export function DeleteAction({
  label,
  confirmText,
  onConfirm,
}: {
  label: string;
  confirmText: string;
  onConfirm: () => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const submitting = useRef(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const close = () => {
    setOpen(false);
    setFailed(false);
    trigger.current?.focus({ preventScroll: true });
  };
  const confirm = async () => {
    if (submitting.current) return;
    submitting.current = true;
    setPending(true);
    setFailed(false);
    try {
      await onConfirm();
      close();
    } catch {
      setFailed(true);
    } finally {
      submitting.current = false;
      setPending(false);
    }
  };
  return (
    <span
      className={styles.root}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open && !submitting.current) {
          event.stopPropagation();
          close();
        }
      }}
    >
      <Popover
        open={open}
        trigger="click"
        placement="top"
        arrow={false}
        destroyOnHidden
        classNames={{ root: styles.popover }}
        onOpenChange={(next) => {
          if (submitting.current) return;
          setOpen(next);
          setFailed(false);
        }}
        afterOpenChange={(next) => {
          if (
            next &&
            !submitting.current &&
            (document.activeElement === trigger.current ||
              document.activeElement === document.body)
          ) {
            cancelButton.current?.focus({ preventScroll: true });
          }
        }}
        content={
          <div
            className={styles.panel}
            role="group"
            aria-label={label}
            onBlur={(event) => {
              if (
                !submitting.current &&
                !event.currentTarget.contains(event.relatedTarget) &&
                event.relatedTarget !== trigger.current
              ) {
                setOpen(false);
              }
            }}
          >
            <span className={styles.label}>{label}</span>
            <button
              ref={cancelButton}
              type="button"
              data-press
              aria-disabled={pending}
              onClick={() => {
                if (!submitting.current) close();
              }}
              aria-label={t("common.cancel", "Cancel")}
            >
              <X size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              data-press
              aria-disabled={pending}
              onClick={() => void confirm()}
              aria-busy={pending}
              className={styles.confirm}
            >
              {pending && (
                <LoaderCircle
                  size={14}
                  className={styles.loading}
                  aria-hidden="true"
                />
              )}
              {confirmText}
            </button>
            {failed && (
              <span className={styles.error} role="alert">
                {t("confirmation.deleteFailed")}
              </span>
            )}
          </div>
        }
      >
        <button
          ref={trigger}
          type="button"
          data-press
          aria-label={label}
          aria-expanded={open}
          aria-disabled={pending}
        >
          <motion.span
            animate={{ rotate: open && !reduced ? -12 : 0 }}
            transition={{ type: "spring", stiffness: 420, damping: 28 }}
          >
            <Trash2 size={17} aria-hidden="true" />
          </motion.span>
        </button>
      </Popover>
    </span>
  );
}

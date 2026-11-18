import { useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Check, LoaderCircle, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./DeleteAction.module.less";

/** Inline confirmation that closes only after the operation resolves. */
export function DeleteAction({
  label,
  onConfirm,
}: {
  label: string;
  onConfirm: () => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const cancel = () => {
    setOpen(false);
    setFailed(false);
    trigger.current?.focus({ preventScroll: true });
  };
  const confirm = async () => {
    if (pending) return;
    setPending(true);
    setFailed(false);
    try {
      await onConfirm();
      cancel();
    } catch {
      setFailed(true);
    } finally {
      setPending(false);
    }
  };
  return (
    <span
      className={styles.root}
      onClick={(event) => event.stopPropagation()}
      onBlur={(event) => {
        if (!pending && !event.currentTarget.contains(event.relatedTarget)) {
          setOpen(false);
          setFailed(false);
        }
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !pending) {
          event.stopPropagation();
          cancel();
        }
      }}
    >
      <button
        ref={trigger}
        type="button"
        data-press
        aria-label={label}
        aria-expanded={open}
        disabled={pending}
        className={styles.trigger}
        onClick={() => (open ? cancel() : setOpen(true))}
      >
        <motion.span
          animate={{ rotate: open && !reduced ? -12 : 0 }}
          transition={{ type: "spring", stiffness: 420, damping: 28 }}
        >
          <Trash2 size={17} />
        </motion.span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.span
            className={styles.panel}
            role="group"
            aria-label={label}
            initial={{ opacity: 0, scale: reduced ? 1 : 0.94 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: reduced ? 1 : 0.96 }}
            transition={{ duration: 0.16 }}
          >
            <span className={styles.label} role={failed ? "alert" : undefined}>
              {failed ? t("common.retry", "Retry") : label}
            </span>
            <button
              type="button"
              data-press
              disabled={pending}
              onClick={() => void confirm()}
              aria-label={t("common.confirm", "Confirm")}
              className={styles.confirm}
            >
              {pending ? (
                <LoaderCircle size={16} className={styles.loading} />
              ) : (
                <Check size={16} />
              )}
            </button>
            <button
              type="button"
              data-press
              disabled={pending}
              onClick={cancel}
              aria-label={t("common.cancel", "Cancel")}
            >
              <X size={16} />
            </button>
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}

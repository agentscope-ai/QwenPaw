import { useEffect, useState } from "react";
import { Modal, type ModalProps } from "antd";
import styles from "./SharedModal.module.less";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

/** Keep the accessible modal mounted until its shared surface returns home. */
export function SharedModal({
  surfaceId,
  open,
  className,
  ...props
}: ModalProps & {
  surfaceId?: string;
}) {
  const reduced = useReducedMotion();
  const [visible, setVisible] = useState(!!open);
  useEffect(() => {
    if (open) setVisible(true);
  }, [open]);
  return (
    <Modal
      centered
      {...props}
      className={`${styles.modal} ${className ?? ""}`}
      open={!!open || visible}
      transitionName=""
      modalRender={(node) => (
        <AnimatePresence
          onExitComplete={() => {
            if (!open) setVisible(false);
          }}
        >
          {open && (
            <motion.div
              key="detail"
              layoutId={reduced ? undefined : surfaceId}
              initial={{ opacity: 0, scale: surfaceId || reduced ? 1 : 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0 }}
              transition={{
                type: "spring",
                stiffness: 360,
                damping: 38,
                opacity: { duration: 0.12 },
              }}
              style={{ borderRadius: 24, background: "var(--app-surface)" }}
            >
              {node}
            </motion.div>
          )}
        </AnimatePresence>
      )}
    />
  );
}

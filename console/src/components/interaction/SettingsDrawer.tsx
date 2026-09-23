import { ConfigProvider, Grid, type DrawerProps } from "antd";
import BottomSheet from "./BottomSheet";
import { SharedModal } from "./SharedModal";
import styles from "./SettingsDrawer.module.less";

/** One editor: centered on desktop, gesture-driven sheet on touch screens. */
export function SettingsDrawer({
  onClose,
  children,
  title,
  footer,
  open,
  width,
  destroyOnHidden,
}: Omit<DrawerProps, "onClose"> & { onClose: () => void }) {
  const screens = Grid.useBreakpoint();
  const content = (
    <ConfigProvider
      getPopupContainer={(trigger) =>
        trigger?.closest<HTMLElement>('[role="dialog"]') ?? document.body
      }
    >
      <div className={styles.form}>{children}</div>
    </ConfigProvider>
  );
  if (screens.md === false) {
    return (
      <BottomSheet
        open={!!open}
        onOpenChange={(next) => {
          if (!next) onClose();
        }}
        title={<div className={styles.editor}>{title}</div>}
        tall
      >
        <div className={styles.editor}>
          {content}
          {footer && <div className={styles.footer}>{footer}</div>}
        </div>
      </BottomSheet>
    );
  }
  return (
    <SharedModal
      centered
      width={
        typeof width === "number" ? Math.max(480, Math.min(width, 960)) : 760
      }
      title={<div className={styles.editor}>{title}</div>}
      open={open}
      onCancel={onClose}
      destroyOnHidden={destroyOnHidden}
      footer={footer ? <div className={styles.editor}>{footer}</div> : null}
      className={styles.editor}
      styles={{
        body: {
          maxHeight: "min(68dvh, 720px)",
          overflowY: "auto",
          overscrollBehavior: "contain",
          padding: "8px 2px",
        },
      }}
    >
      {content}
    </SharedModal>
  );
}

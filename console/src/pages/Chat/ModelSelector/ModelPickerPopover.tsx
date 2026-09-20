import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Drawer, Popover } from "antd";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

/** Keep the menu anchored and its scroll viewport stable while browsing. */
export function ModelPickerPopover({
  open,
  onOpenChange,
  content,
  children,
  picker = true,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  content: ReactNode;
  children: ReactNode;
  picker?: boolean;
}) {
  const { t } = useTranslation();
  const anchor = useRef<HTMLSpanElement>(null);
  const [layout, setLayout] = useState({
    height: 480,
    above: false,
    mobile: false,
  });
  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const rect = anchor.current?.getBoundingClientRect();
      if (!rect) return;
      const viewport = window.visualViewport;
      const height = viewport?.height ?? window.innerHeight;
      const top = viewport?.offsetTop ?? 0;
      const above = rect.top - top - 48;
      const below = top + height - rect.bottom - 48;
      setLayout({
        height: Math.min(480, Math.max(above, below)),
        above: above > below,
        mobile: window.innerWidth <= 600,
      });
    };
    measure();
    window.addEventListener("resize", measure);
    window.visualViewport?.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("resize", measure);
      window.visualViewport?.removeEventListener("resize", measure);
    };
  }, [open]);
  const panel = (
    <div
      className={styles.pickerViewport}
      style={{
        width: picker ? 400 : 320,
        height: picker ? layout.height : undefined,
      }}
    >
      {content}
    </div>
  );
  return (
    <>
      <Popover
        open={open && !layout.mobile}
        onOpenChange={onOpenChange}
        trigger="click"
        placement={layout.above ? "topLeft" : "bottomLeft"}
        autoAdjustOverflow
        overlayClassName={styles.pickerOverlay}
        destroyOnHidden
        content={panel}
      >
        <span ref={anchor} className={styles.pickerAnchor}>
          {children}
        </span>
      </Popover>
      <Drawer
        open={open && layout.mobile}
        onClose={() => onOpenChange(false)}
        placement="bottom"
        height={picker ? "min(560px, calc(100dvh - 12px))" : "auto"}
        title={null}
        closeIcon={<X size={18} aria-label={t("common.close")} />}
        className={styles.pickerSheet}
        destroyOnHidden
      >
        {content}
      </Drawer>
    </>
  );
}

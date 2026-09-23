import {
  lazy,
  Suspense,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Popover } from "antd";

import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

const BottomSheet = lazy(() => import("@/components/interaction/BottomSheet"));

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
    mobile: window.innerWidth <= 600,
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
      role="dialog"
      aria-label={t(
        picker ? "modelSelector.selectModel" : "thinkingControl.title",
      )}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onOpenChange(false);
          anchor.current
            ?.querySelector("button")
            ?.focus({ preventScroll: true });
        }
      }}
      className={styles.pickerViewport}
      style={{
        width: 360,
        borderRadius: 20,
        background: "var(--app-surface)",
        maxHeight: Math.max(120, layout.height),
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
        {content}
      </div>
    </div>
  );
  return (
    <>
      <Popover
        arrow={false}
        open={open && !layout.mobile}
        onOpenChange={onOpenChange}
        trigger="click"
        placement={layout.above ? "topLeft" : "bottomLeft"}
        transitionName="qwenpaw-picker-fade"
        autoAdjustOverflow
        overlayClassName={styles.pickerOverlay}
        destroyOnHidden
        content={panel}
      >
        <span
          ref={anchor}
          className={styles.pickerAnchor}
          style={{ position: "relative", isolation: "isolate" }}
        >
          {children}
        </span>
      </Popover>
      {layout.mobile && (
        <Suspense fallback={null}>
          <BottomSheet
            open={open}
            onOpenChange={onOpenChange}
            title={t(
              picker ? "modelSelector.selectModel" : "thinkingControl.title",
            )}
            tall={picker}
            onCloseFocus={() =>
              anchor.current
                ?.querySelector("button")
                ?.focus({ preventScroll: true })
            }
          >
            {content}
          </BottomSheet>
        </Suspense>
      )}
    </>
  );
}

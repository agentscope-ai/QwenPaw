import { useState, type ReactNode } from "react";
import { Drawer } from "vaul";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./BottomSheet.module.less";

export default function BottomSheet({
  open,
  onOpenChange,
  title,
  children,
  tall = false,
  initialSnap = 0.9,
  onCloseFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  tall?: boolean;
  initialSnap?: number;
  onCloseFocus?: () => void;
}) {
  const { t } = useTranslation();
  const [snap, setSnap] = useState<number | string | null>(initialSnap);
  return (
    <Drawer.Root
      open={open}
      onOpenChange={onOpenChange}
      snapPoints={tall ? [0.5, 0.9] : undefined}
      activeSnapPoint={tall ? snap : undefined}
      setActiveSnapPoint={setSnap}
      fixed
      repositionInputs
      noBodyStyles
      autoFocus
    >
      <Drawer.Portal>
        <Drawer.Overlay className={styles.overlay} />
        <Drawer.Content
          className={styles.sheet}
          aria-describedby={undefined}
          style={tall ? { height: "100dvh", maxHeight: "100dvh" } : undefined}
          onCloseAutoFocus={(event) => {
            if (onCloseFocus) {
              event.preventDefault();
              onCloseFocus();
            }
          }}
        >
          <Drawer.Handle className={styles.handle} />
          <header className={styles.header}>
            <Drawer.Title>{title}</Drawer.Title>
            <Drawer.Close aria-label={t("common.close")}>
              <X size={18} />
            </Drawer.Close>
          </header>
          <div
            className={styles.content}
            style={
              tall && typeof snap === "number"
                ? { maxHeight: `calc(${snap * 100}dvh - 68px)` }
                : undefined
            }
          >
            {children}
          </div>
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  );
}

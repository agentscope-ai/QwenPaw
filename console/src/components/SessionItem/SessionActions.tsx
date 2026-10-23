import {
  lazy,
  useEffect,
  Suspense,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { Popover } from "antd";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowLeft, Check, ChevronRight, Folder } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useIsMobile } from "../../hooks/useIsMobile";
import { InteractiveCard } from "../interaction/InteractiveCard";
import styles from "./sessionActions.module.less";

const BottomSheet = lazy(() => import("../interaction/BottomSheet"));
type Action = {
  key?: string;
  type?: "divider";
  icon?: ReactNode;
  label?: string;
  danger?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children?: Action[];
};

/** One anchored surface for conversation actions and its group picker. */
export default function SessionActions({
  children,
  items,
  name,
  context = false,
  onOpenChange,
}: {
  children: ReactElement;
  items: Action[];
  name: string;
  context?: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const mobile = useIsMobile();
  const reduced = useReducedMotion();
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [visible, setVisible] = useState(false);
  const [groupPage, setGroupPage] = useState(false);
  const focus = useRef<HTMLElement | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [fold, setFold] = useState("inset(0% 75% 85% 0% round 20px)");
  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => {
      const bounds = panel.current?.getBoundingClientRect();
      const source = focus.current?.getBoundingClientRect();
      if (bounds && source) {
        const fromLeft =
          source.left + source.width / 2 < bounds.left + bounds.width / 2;
        const fromTop =
          source.top + source.height / 2 < bounds.top + bounds.height / 2;
        setFold(
          `inset(${fromTop ? "0%" : "85%"} ${fromLeft ? "75%" : "0%"} ${
            fromTop ? "85%" : "0%"
          } ${fromLeft ? "0%" : "75%"} round 20px)`,
        );
      }
      panel.current
        ?.querySelector<HTMLButtonElement>(
          'button[role="menuitem"]:not(:disabled)',
        )
        ?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [open, groupPage]);
  const change = (next: boolean) => {
    if (next) {
      focus.current = document.activeElement as HTMLElement;
      setVisible(true);
    }
    setOpen(next);
    onOpenChange(next);
  };
  const finish = () => {
    if (open) return;
    setVisible(false);
    setGroupPage(false);
    focus.current?.focus({ preventScroll: true });
  };
  const actions = items.filter((item) => item.key);
  const move = actions.find((item) => item.key === "move");
  const entries = groupPage ? move?.children ?? [] : actions;
  const body = (
    <InteractiveCard
      tilt={2}
      className={styles.card}
      onClick={(event) => event.stopPropagation()}
    >
      <motion.div
        layout={!reduced}
        transition={{ type: "spring", bounce: 0, duration: 0.3 }}
      >
        <header className={styles.heading} data-group={groupPage}>
          {groupPage && (
            <button
              data-press
              aria-label={t("common.back", "Back")}
              onClick={() => setGroupPage(false)}
            >
              <ArrowLeft size={16} />
            </button>
          )}
          <span>{groupPage ? move?.label : name}</span>
        </header>
        <AnimatePresence initial={false} mode="popLayout">
          <motion.div
            key={groupPage ? "groups" : "actions"}
            role="menu"
            aria-label={groupPage ? move?.label : name}
            className={groupPage ? styles.groups : styles.actions}
            initial={{ opacity: 0, x: reduced ? 0 : 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: reduced ? 0 : -8 }}
            transition={{ duration: reduced ? 0 : 0.14 }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.stopPropagation();
                change(false);
                return;
              }
              if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key))
                return;
              event.preventDefault();
              const buttons = [
                ...event.currentTarget.querySelectorAll<HTMLButtonElement>(
                  "button:not(:disabled)",
                ),
              ];
              const current = buttons.indexOf(
                document.activeElement as HTMLButtonElement,
              );
              const next =
                event.key === "Home"
                  ? 0
                  : event.key === "End"
                  ? buttons.length - 1
                  : (current +
                      (event.key === "ArrowUp" ? -1 : 1) +
                      buttons.length) %
                    buttons.length;
              buttons[next]?.focus();
            }}
          >
            {entries.map((item, index) => (
              <motion.button
                key={item.key}
                type="button"
                role="menuitem"
                data-press
                disabled={item.disabled}
                className={`${styles.action} ${
                  item.danger ? styles.danger : ""
                } ${!groupPage && index > 3 ? styles.wide : ""}`}
                initial={reduced ? false : { opacity: 0, y: 7 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  type: "spring",
                  stiffness: 420,
                  damping: 30,
                  delay: reduced ? 0 : index * 0.02,
                }}
                onClick={(event) => {
                  event.stopPropagation();
                  if (item.children) {
                    setGroupPage(true);
                    return;
                  }
                  change(false);
                  item.onClick?.();
                }}
              >
                {item.icon ?? <Folder size={17} />}
                <span>{item.label}</span>
                {item.children && <ChevronRight size={13} />}
                {item.disabled && <Check size={14} />}
              </motion.button>
            ))}
            {groupPage && !entries.length && (
              <p>{t("chat.group.noGroups", "No groups yet")}</p>
            )}
          </motion.div>
        </AnimatePresence>
      </motion.div>
    </InteractiveCard>
  );
  return (
    <>
      <Popover
        open={!mobile && visible}
        onOpenChange={change}
        trigger={context ? ["contextMenu"] : ["click"]}
        placement="bottomRight"
        arrow={false}
        transitionName=""
        classNames={{ root: styles.popover }}
        content={
          <motion.div
            ref={panel}
            initial={
              reduced
                ? false
                : {
                    opacity: 0,
                    clipPath: fold,
                    y: -4,
                  }
            }
            animate={
              open
                ? {
                    opacity: 1,
                    clipPath: "inset(0% 0% 0% 0% round 20px)",
                    y: 0,
                  }
                : {
                    opacity: 0,
                    clipPath: fold,
                    y: -4,
                  }
            }
            transition={{
              type: "spring",
              bounce: 0,
              duration: reduced ? 0 : open ? 0.3 : 0.22,
              opacity: { duration: reduced ? 0 : 0.16 },
            }}
            onAnimationComplete={finish}
            onClick={(event) => event.stopPropagation()}
          >
            {body}
          </motion.div>
        }
      >
        {children}
      </Popover>
      {mobile && visible && (
        <Suspense fallback={null}>
          <BottomSheet
            open={open}
            onOpenChange={change}
            title={name}
            onCloseFocus={finish}
          >
            {body}
          </BottomSheet>
        </Suspense>
      )}
    </>
  );
}

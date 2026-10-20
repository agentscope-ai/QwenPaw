import {
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { motion, useReducedMotion } from "motion/react";
import { Button } from "antd";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../../api/request";
import type { createSdkSessionAdapter } from "../sdkSessionAdapter";
import styles from "./ChatSessionTransition.module.less";

type Props = {
  adapter: ReturnType<typeof createSdkSessionAdapter>;
  sessionId?: string;
  pending?: boolean;
  error?: unknown;
  onRetry?: () => void;
  children: ReactNode;
};

function useSessionReady({ adapter, sessionId, pending, error }: Props) {
  useSyncExternalStore(adapter.subscribe, adapter.getSnapshot);
  return !pending && !error && adapter.isReady(sessionId);
}

/** Keep SDK identity and loading intact; only transition its presented surface. */
export function ChatSessionTransition(props: Props) {
  const ready = useSessionReady(props);
  const failed = !!props.error || props.adapter.hasFailed(props.sessionId);
  const reduced = useReducedMotion();
  const { t } = useTranslation();
  const errorKey =
    props.error instanceof ApiError && props.error.status === 404
      ? "chat.routeNotFound"
      : props.error instanceof ApiError && props.error.status === 409
      ? "chat.routeAmbiguous"
      : "chat.historyLoadFailed";
  const surface = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (surface.current) surface.current.inert = !ready;
  }, [ready]);
  return (
    <div className={styles.container} aria-busy={!ready && !failed}>
      <motion.div
        ref={surface}
        className={styles.surface}
        style={{ visibility: ready ? "visible" : "hidden" }}
        initial={false}
        animate={{ opacity: ready ? 1 : 0 }}
        transition={{ duration: reduced ? 0 : 0.18, ease: "easeOut" }}
      >
        {props.children}
      </motion.div>
      {!ready && (
        <div
          className={`${styles.status} ${failed ? styles.error : ""}`}
          role={failed ? "alert" : "status"}
        >
          <span>{t(failed ? errorKey : "common.loading")}</span>
          {failed && props.onRetry && (
            <Button size="small" onClick={props.onRetry}>
              {t("common.retry")}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** An empty message list during hydration is not a new conversation. */
export function ReadyChatWelcome(props: Props) {
  return useSessionReady(props) ? props.children : null;
}

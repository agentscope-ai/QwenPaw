import {
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { motion, useReducedMotion } from "motion/react";
import { useTranslation } from "react-i18next";
import type { createSdkSessionAdapter } from "../sdkSessionAdapter";
import styles from "./ChatSessionTransition.module.less";

type Props = {
  adapter: ReturnType<typeof createSdkSessionAdapter>;
  sessionId?: string;
  children: ReactNode;
};

function useSessionReady({ adapter, sessionId }: Props) {
  useSyncExternalStore(adapter.subscribe, adapter.getSnapshot);
  return adapter.isReady(sessionId);
}

/** Keep SDK identity and loading intact; only transition its presented surface. */
export function ChatSessionTransition(props: Props) {
  const ready = useSessionReady(props);
  const failed = props.adapter.hasFailed(props.sessionId);
  const reduced = useReducedMotion();
  const { t } = useTranslation();
  const surface = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (surface.current) surface.current.inert = !ready;
  }, [ready]);
  return (
    <div className={styles.container} aria-busy={!ready && !failed}>
      <motion.div
        ref={surface}
        className={styles.surface}
        initial={false}
        animate={{ opacity: failed ? 0 : ready ? 1 : 0.55 }}
        transition={{ duration: reduced ? 0 : 0.18, ease: "easeOut" }}
      >
        {props.children}
      </motion.div>
      {!ready && (
        <div className={styles.status} role={failed ? "alert" : "status"}>
          {t(failed ? "chat.historyLoadFailed" : "common.loading")}
        </div>
      )}
    </div>
  );
}

/** An empty message list during hydration is not a new conversation. */
export function ReadyChatWelcome(props: Props) {
  return useSessionReady(props) ? props.children : null;
}

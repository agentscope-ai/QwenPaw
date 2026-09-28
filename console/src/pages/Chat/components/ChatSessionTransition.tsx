import {
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";
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

/** Keep stale content visible but inert until the SDK adopts the target. */
export function ChatSessionTransition(props: Props) {
  const ready = useSessionReady(props);
  const failed = props.adapter.hasFailed(props.sessionId);
  const { t } = useTranslation();
  const surface = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (surface.current) surface.current.inert = !ready;
  }, [ready]);
  return (
    <div className={styles.container} aria-busy={!ready && !failed}>
      <div ref={surface} className={styles.surface}>
        {props.children}
      </div>
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

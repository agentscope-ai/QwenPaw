import {
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";
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

/** Keep stale content visible but inert until the SDK adopts the target. */
export function ChatSessionTransition(props: Props) {
  const ready = useSessionReady(props);
  const failed = !!props.error || props.adapter.hasFailed(props.sessionId);
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
      <div ref={surface} className={styles.surface}>
        {props.children}
      </div>
      {!ready && (
        <div
          className={`${styles.status} ${failed ? styles.error : ""}`}
          role={failed ? "alert" : "status"}
        >
          <span>{t(failed ? errorKey : "common.loading")}</span>
          {failed && props.onRetry && (
            <Button size="small" type="default" onClick={props.onRetry}>
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

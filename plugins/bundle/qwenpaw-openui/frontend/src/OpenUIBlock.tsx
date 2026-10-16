import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type SyntheticEvent,
} from "react";
import {
  Renderer,
  type ActionEvent,
  type OpenUIError,
} from "@openuidev/react-lang";
import { ThemeProvider } from "@openuidev/react-ui";
import type { ChatCodeBlockProps } from "./qwenpaw-host";
import { getHost } from "./host";
import { dispatchAction } from "./actions";
import { useOpenUIStyles } from "./styles";
import { createUIStream } from "./streaming";
import { streamingLibrary } from "./library";
import { useOpenUITheme } from "./theme";

export function OpenUIBlock(props: ChatCodeBlockProps) {
  const { source, isStreaming, agentId, sessionId } = props;
  const api = getHost();
  const theme = api.host.useTheme();
  const themes = useOpenUITheme();
  const locale = api.host.useLocale();
  const zh = locale.startsWith("zh");
  const [failure, setFailure] = useState<{ source: string; message: string }>();
  const [actionError, setActionError] = useState("");
  const [pending, setPending] = useState(false);
  const inFlight = useRef(0);
  const stream = useMemo(createUIStream, []);
  const frame = useMemo(
    () => stream(source, isStreaming),
    [stream, source, isStreaming],
  );
  useOpenUIStyles();

  const onError = useCallback(
    (errors: OpenUIError[]) => {
      if (isStreaming) return;
      const error = errors.find((item) => item.severity !== "warning");
      if (error) setFailure({ source, message: error.message });
    },
    [source, isStreaming],
  );

  const onAction = useCallback(
    (event: ActionEvent) => {
      if (isStreaming) return;
      // One Action can synchronously dispatch several host events. Admit all
      // its steps; guard subsequent user gestures at the DOM boundary instead.
      inFlight.current += 1;
      setPending(true);
      setActionError("");
      void dispatchAction(api, { agentId, sessionId }, event)
        .catch((error: unknown) => {
          setActionError(
            error instanceof Error ? error.message : String(error),
          );
        })
        .finally(() => {
          inFlight.current -= 1;
          if (inFlight.current === 0) setPending(false);
        });
    },
    [api, agentId, sessionId, isStreaming],
  );

  const guardPendingInteraction = (event: SyntheticEvent) => {
    if (inFlight.current > 0) {
      event.preventDefault();
      event.stopPropagation();
    }
  };

  const error = frame.error || failure?.source === source;
  return (
    <section
      className="qwenpaw-openui"
      data-openui-block={props.blockId}
      aria-busy={isStreaming || pending}
    >
      <ThemeProvider mode={theme} {...themes} cssSelector=".qwenpaw-openui">
        <fieldset
          hidden={!!error}
          disabled={pending}
          className="qwenpaw-openui-content"
          onClickCapture={guardPendingInteraction}
          onKeyDownCapture={guardPendingInteraction}
        >
          <Renderer
            response={frame.response}
            library={streamingLibrary}
            isStreaming={isStreaming}
            onAction={onAction}
            onError={onError}
            toolProvider={null}
            publishObservability={false}
          />
        </fieldset>
      </ThemeProvider>
      {error ? (
        <p role="alert">
          {zh
            ? "交互界面暂时无法显示，请让助手重新生成。"
            : "This interface could not be displayed. Ask the assistant to generate it again."}
        </p>
      ) : isStreaming ? (
        <div className="qwenpaw-openui-progress" role="status">
          {zh ? "正在生成交互界面…" : "Generating interactive UI…"}
        </div>
      ) : null}
      {pending && <span role="status">{zh ? "正在提交…" : "Submitting…"}</span>}
      {actionError && <p role="alert">{actionError}</p>}
    </section>
  );
}

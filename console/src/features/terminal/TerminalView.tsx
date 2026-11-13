import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import type { TerminalApi, TerminalInfo } from "./terminalApi";
import styles from "./TerminalDock.module.less";
import { terminalInputChunks } from "./terminalInput";

export default function TerminalView({
  terminal,
  api,
  isDark,
  onExit,
}: {
  terminal: TerminalInfo;
  api: TerminalApi;
  isDark: boolean;
  onExit?: (terminalId: string, exitCode: number | null) => void;
}) {
  const { t } = useTranslation();
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<Terminal>();
  const [error, setError] = useState("");
  const [exited, setExited] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!host.current) return;
    const controller = new AbortController();
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      scrollback: 5000,
      fontFamily: 'ui-monospace, "SFMono-Regular", Consolas, monospace',
      allowProposedApi: false,
    });
    instance.current = term;
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host.current);
    // A program must not read/write the system clipboard via OSC 52.
    const clipboard = term.parser.registerOscHandler(52, () => true);
    let frame = 0;
    let previousSize = "";
    let pendingSize: [number, number] | undefined;
    let resizing = false;
    let writes = Promise.resolve();
    let queued = 0;
    let failed = false;
    const fail = (cause: unknown) => {
      if (controller.signal.aborted) return;
      failed = true;
      setError(
        cause instanceof Error ? cause.message.split(" - ")[0] : String(cause),
      );
      term.options.disableStdin = true;
    };
    const flushResize = async () => {
      if (resizing) return;
      resizing = true;
      try {
        while (pendingSize && !controller.signal.aborted) {
          const [rows, cols] = pendingSize;
          pendingSize = undefined;
          await api.resize(terminal.id, rows, cols);
        }
      } catch (cause) {
        fail(cause);
      } finally {
        resizing = false;
      }
    };
    const resize = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!host.current?.clientWidth || !host.current.clientHeight) return;
        fit.fit();
        const size = `${term.rows}:${term.cols}`;
        if (size === previousSize) return;
        previousSize = size;
        pendingSize = [
          Math.max(2, Math.min(500, term.rows)),
          Math.max(2, Math.min(500, term.cols)),
        ];
        void flushResize();
      });
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host.current);
    resize();
    const input = term.onData((data) => {
      if (failed) return;
      if (queued + data.length > 262144) {
        fail(
          new Error(
            t(
              "terminal.inputTooLarge",
              "Input is too large; reconnect to continue.",
            ),
          ),
        );
        return;
      }
      queued += data.length;
      writes = writes
        .then(async () => {
          for (const chunk of terminalInputChunks(data)) {
            if (failed) return;
            await api.input(terminal.id, chunk);
          }
        })
        .catch((cause) => {
          failed = true;
          fail(cause);
        })
        .finally(() => {
          queued -= data.length;
        });
    });
    setError("");
    setExited(false);
    void (async () => {
      let cursor = 0;
      while (!controller.signal.aborted) {
        const output = await api.output(terminal.id, cursor, controller.signal);
        if (controller.signal.aborted) return;
        if (output.reset) term.reset();
        if (output.data) {
          await new Promise<void>((resolve) =>
            term.write(output.data, resolve),
          );
        }
        cursor = output.cursor;
        if (output.exited) {
          setExited(true);
          onExit?.(terminal.id, output.exit_code);
          term.options.disableStdin = true;
          break;
        }
      }
    })().catch(fail);
    term.focus();
    return () => {
      controller.abort();
      cancelAnimationFrame(frame);
      observer.disconnect();
      input.dispose();
      clipboard.dispose();
      term.dispose();
      instance.current = undefined;
    };
  }, [api, terminal.id, attempt, t, onExit]);

  useEffect(() => {
    if (instance.current)
      instance.current.options.theme = isDark
        ? {
            background: "#17191c",
            foreground: "#d8dce3",
            cursor: "#d8dce3",
            selectionBackground: "#454b59",
          }
        : {
            background: "#fafafa",
            foreground: "#20242b",
            cursor: "#20242b",
            selectionBackground: "#d7e1ef",
          };
  }, [isDark, attempt, api, terminal.id]);

  return (
    <div className={styles.view} data-dark={isDark}>
      <div className={styles.screen}>
        <div ref={host} className={styles.terminalHost} />
      </div>
      {error ? (
        <div role="alert" className={styles.status}>
          <span>{error}</span>
          <button onClick={() => setAttempt((value) => value + 1)}>
            {t("terminal.reconnect", "Reconnect")}
          </button>
        </div>
      ) : exited ? (
        <div className={styles.status}>
          {t("terminal.exited", "Process exited")}
        </div>
      ) : null}
    </div>
  );
}

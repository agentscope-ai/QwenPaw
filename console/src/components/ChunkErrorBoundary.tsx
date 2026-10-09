import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";
import { Button, Result, Space } from "antd";
import { Check, Copy, RotateCw } from "lucide-react";
import i18n from "../i18n";
import { hubApi } from "../api/modules/hub";
import {
  isChunkLoadError,
  reloadAfterChunkError,
} from "../utils/chunkRecovery";
import { resetFailedLazyImports } from "../utils/lazyWithRetry";
import {
  captureChunkDiagnostic,
  failedResourceUrl,
  readChunkDiagnostic,
  recheckChunkResource,
  saveChunkDiagnostic,
} from "../utils/chunkDiagnostics";
import type { ChunkDiagnostic } from "../utils/chunkDiagnostics";
import { copyText } from "../utils/clipboard";
import styles from "./ChunkErrorBoundary.module.less";

interface Props {
  children: ReactNode;
  /** When this key changes the error state is automatically cleared. */
  resetKey?: string;
  canRestartRuntime?: boolean;
}

interface State {
  hasError: boolean;
  isChunkError: boolean;
  restarting: boolean;
  restartError: string;
  diagnostic: ChunkDiagnostic | null;
  previousDiagnostic: ChunkDiagnostic | null;
  copied: boolean;
  copyFailed: boolean;
}

/**
 * Error boundary that wraps lazily-loaded route chunks.
 *
 * - **Chunk-load errors** reset rejected imports and refresh once per build.
 *   Persistent failures retain a targeted fallback and manual refresh.
 * - **Other render errors** (runtime bugs) get a generic fallback so the
 *   rest of the app remains functional.
 *
 * Pass a `resetKey` derived from the current route so the boundary
 * automatically recovers when the user navigates to a different page.
 */
export class ChunkErrorBoundary extends Component<Props, State> {
  state: State = {
    hasError: false,
    isChunkError: false,
    restarting: false,
    restartError: "",
    diagnostic: null,
    previousDiagnostic: null,
    copied: false,
    copyFailed: false,
  };

  private diagnosticGeneration = 0;

  static getDerivedStateFromError(error: unknown): State {
    return {
      hasError: true,
      isChunkError: isChunkLoadError(error),
      restarting: false,
      restartError: "",
      diagnostic: null,
      previousDiagnostic: null,
      copied: false,
      copyFailed: false,
    };
  }

  componentDidUpdate(prevProps: Readonly<Props>) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.diagnosticGeneration += 1;
      this.setState({
        hasError: false,
        isChunkError: false,
        restarting: false,
        restartError: "",
        diagnostic: null,
        previousDiagnostic: null,
        copied: false,
        copyFailed: false,
      });
    }
  }

  componentWillUnmount() {
    this.diagnosticGeneration += 1;
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    const label = isChunkLoadError(error) ? "Chunk load error" : "Render error";
    console.error(`${label}:`, error, info);
    if (isChunkLoadError(error)) {
      resetFailedLazyImports(error);
      void this.diagnoseChunkError(error);
    }
  }

  diagnoseChunkError = async (error: Error) => {
    const generation = ++this.diagnosticGeneration;
    const diagnostic = captureChunkDiagnostic(error);
    const previous = readChunkDiagnostic();
    saveChunkDiagnostic(diagnostic);
    this.setState({
      diagnostic,
      previousDiagnostic:
        previous?.automaticReloadAttempted && previous.page === diagnostic.page
          ? previous
          : null,
    });
    const recheck = await recheckChunkResource(failedResourceUrl(error));
    if (generation !== this.diagnosticGeneration || !this.state.hasError)
      return;
    const completed = { ...diagnostic, recheck };
    saveChunkDiagnostic(completed);
    this.setState({ diagnostic: completed, copied: false });
    reloadAfterChunkError(() => {
      completed.automaticReloadAttempted = true;
      saveChunkDiagnostic(completed);
    });
  };

  copyDiagnostic = async () => {
    this.setState({ copied: false, copyFailed: false });
    try {
      await copyText(this.diagnosticText());
      this.setState({ copied: true });
    } catch {
      this.setState({ copyFailed: true });
    }
  };

  diagnosticText() {
    return JSON.stringify(
      {
        current: this.state.diagnostic,
        beforeAutomaticReload: this.state.previousDiagnostic,
      },
      null,
      2,
    );
  }

  restartRuntime = async () => {
    this.setState({ restarting: true, restartError: "" });
    try {
      await hubApi.restartOwnRuntime();
      window.location.reload();
    } catch (error: unknown) {
      this.setState({
        restarting: false,
        restartError:
          error instanceof Error
            ? error.message
            : i18n.t("account.runtimeRestartFailed"),
      });
    }
  };

  render() {
    if (this.state.hasError) {
      const titleKey = this.state.isChunkError
        ? "chunkError.title"
        : "chunkError.genericTitle";
      const subTitleKey = this.state.isChunkError
        ? "chunkError.subTitle"
        : "chunkError.genericSubTitle";

      return (
        <Result
          status="error"
          title={i18n.t(titleKey)}
          subTitle={this.state.restartError || i18n.t(subTitleKey)}
          extra={
            <div className={styles.recovery} style={{ margin: 0 }}>
              {this.state.diagnostic && (
                <div className={styles.diagnostics}>
                  <details>
                    <summary>{i18n.t("chunkError.details")}</summary>
                    <p role="status" className={styles.observation}>
                      {i18n.t(
                        this.state.diagnostic.recheck
                          ? `chunkError.observations.${this.state.diagnostic.recheck.outcome}`
                          : "chunkError.checking",
                      )}
                    </p>
                    <p className={styles.note}>
                      {i18n.t("chunkError.recheckNote")}
                    </p>
                    <pre>{this.diagnosticText()}</pre>
                  </details>
                </div>
              )}
              <Space wrap className={styles.actions}>
                {this.state.diagnostic && (
                  <Button
                    icon={
                      this.state.copied ? (
                        <Check size={16} />
                      ) : (
                        <Copy size={16} />
                      )
                    }
                    onClick={this.copyDiagnostic}
                  >
                    {i18n.t(
                      this.state.copied
                        ? "chunkError.copied"
                        : "chunkError.copy",
                    )}
                  </Button>
                )}
                <Button type="primary" onClick={() => window.location.reload()}>
                  {i18n.t("chunkError.reload")}
                </Button>
                {this.props.canRestartRuntime && (
                  <Button
                    icon={<RotateCw size={16} />}
                    loading={this.state.restarting}
                    onClick={this.restartRuntime}
                  >
                    {i18n.t("account.runtimeRestart")}
                  </Button>
                )}
              </Space>
              {this.state.copyFailed && (
                <p role="alert" className={styles.note}>
                  {i18n.t("chunkError.copyFailed")}
                </p>
              )}
            </div>
          }
          style={{ marginTop: "10vh" }}
        />
      );
    }
    return this.props.children;
  }
}

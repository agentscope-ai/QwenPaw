import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";
import { Button, Result, Space } from "antd";
import { Check, Copy, RotateCw } from "lucide-react";
import i18n from "../i18n";
import { hubApi } from "../api/modules/hub";
import {
  isChunkLoadError,
  isErrorLike,
  reloadAfterChunkError,
  type ErrorLike,
} from "../utils/chunkRecovery";
import {
  captureChunkDiagnostic,
  failedResourceUrl,
  readBeforeAutomaticReloadDiagnostic,
  recheckChunkResource,
  saveChunkDiagnostic,
  type ChunkDiagnostic,
  type ResourceRecheck,
} from "../utils/chunkDiagnostics";
import { resetFailedLazyImports } from "../utils/lazyWithRetry";
import { copyText } from "../utils/clipboard";
import styles from "./ChunkErrorBoundary.module.less";

/** Give up retrying after this many attempts and fall back to a reload. */
export const MAX_RENDER_ERROR_RETRIES = 2;

interface Props {
  children: ReactNode;
  /** Change to reset the boundary when the user navigates to a new page. */
  resetKey?: string;
  /** When true, surface the "Restart runtime" button for Hub users. */
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
  /**
   * Whether the error looks like a transient DOM-mutation race.
   *
   * In the original PR #7889 this was gated on a `NotFoundError` /
   * `HierarchyRequestError` heuristic. Per the rebase review we now rely on
   * `isErrorLike` (cross-realm-safe `instanceof Error`) so that any
   * Error-like render error is considered for in-place retry; the retry
   * budget (`MAX_RENDER_ERROR_RETRIES`) prevents a permanently broken page
   * from looping forever.
   */
  isRetryableError: boolean;
  /** How many times the user asked to re-render after a render error. */
  retryCount: number;
}

/**
 * Error boundary that wraps lazily-loaded route chunks.
 *
 * - **Chunk-load errors** (stale cache, network, deploy race) get a targeted
 *   message suggesting the user reload.
 * - **Other render errors** get a generic fallback so the rest of the app
 *   remains functional. Transient races additionally offer an in-place retry,
 *   since a full page reload is unnecessary for them.
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
    isRetryableError: false,
    retryCount: 0,
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
      isRetryableError: isErrorLike(error),
      retryCount: 0,
    };
  }

  componentDidUpdate(prevProps: Readonly<Props>) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.diagnosticGeneration += 1;
      this.reset();
    }
  }

  componentWillUnmount() {
    this.diagnosticGeneration += 1;
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    const label = isChunkLoadError(error) ? "Chunk load error" : "Render error";
    console.error(`${label}:`, error, info);
    if (isChunkLoadError(error)) {
      resetFailedLazyImports(error);
      void this.diagnoseChunkError(error);
    }
  }

  diagnoseChunkError = async (error: ErrorLike) => {
    const generation = ++this.diagnosticGeneration;
    const diagnostic = captureChunkDiagnostic(error);
    const previous = readBeforeAutomaticReloadDiagnostic(diagnostic.page);
    saveChunkDiagnostic(diagnostic);
    this.setState({
      diagnostic,
      previousDiagnostic: previous,
    });
    const recheck = await recheckChunkResource(failedResourceUrl(error));
    if (generation !== this.diagnosticGeneration || !this.state.hasError) {
      return;
    }
    const completed = { ...diagnostic, recheck };
    saveChunkDiagnostic(completed);
    this.setState({ diagnostic: completed, copied: false });
    reloadAfterChunkError((decision) => {
      completed.automaticReloadAttempted = decision.reason === "reload";
      completed.automaticReload = decision;
      saveChunkDiagnostic(completed);
      this.setState({ diagnostic: { ...completed } });
    });
  };

  private reset = () => {
    this.setState({
      hasError: false,
      isChunkError: false,
      restarting: false,
      restartError: "",
      diagnostic: null,
      previousDiagnostic: null,
      copied: false,
      copyFailed: false,
      isRetryableError: false,
      retryCount: 0,
    });
  };

  /** Re-render the same subtree without reloading the page. */
  retryRender = () => {
    this.setState((prev) => ({
      hasError: false,
      isChunkError: false,
      restartError: "",
      isRetryableError: prev.isRetryableError,
      retryCount: prev.retryCount + 1,
    }));
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

      const canRetry =
        this.state.isRetryableError &&
        !this.state.isChunkError &&
        this.state.retryCount < MAX_RENDER_ERROR_RETRIES;

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
                {canRetry && (
                  <Button type="primary" onClick={this.retryRender}>
                    {i18n.t("chunkError.retry")}
                  </Button>
                )}
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
                <Button
                  type={canRetry ? "default" : "primary"}
                  onClick={() => window.location.reload()}
                >
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

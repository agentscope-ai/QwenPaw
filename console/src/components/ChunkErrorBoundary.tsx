import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";
import { Button, Result, Space } from "antd";
import { RotateCw } from "lucide-react";
import i18n from "../i18n";
import { hubApi } from "../api/modules/hub";

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
  /** Whether the error looks like a transient DOM-mutation race. */
  isRetryableError: boolean;
  /** How many times the user asked to re-render after a render error. */
  retryCount: number;
}

/** Heuristic: does this look like a failed dynamic import? */
function isChunkLoadError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const msg = error.message.toLowerCase();
  return (
    msg.includes("loading chunk") ||
    msg.includes("loading css chunk") ||
    msg.includes("dynamically imported module") ||
    msg.includes("failed to fetch") ||
    error.name === "ChunkLoadError"
  );
}

/**
 * Errors raised by React's DOM commit phase rather than by user code, when
 * something mutated the real DOM behind React's back — a browser UI layer
 * wrapping a React-managed text node, an extension injecting nodes, a
 * WebView shell. They surface as `NotFoundError` / `HierarchyRequestError`
 * from `insertBefore` / `removeChild` and are usually transient: the same
 * tree commits fine on the next attempt.
 */
function isDomMutationError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  if (error.name === "NotFoundError") return true;
  if (error.name === "HierarchyRequestError") return true;
  const msg = error.message.toLowerCase();
  return (
    msg.includes("insertbefore") ||
    msg.includes("removechild") ||
    msg.includes("appendchild") ||
    msg.includes("not a child of this node")
  );
}

/** Give up retrying after this many attempts and fall back to a reload. */
export const MAX_RENDER_ERROR_RETRIES = 2;

/**
 * Error boundary that wraps lazily-loaded route chunks.
 *
 * - **Chunk-load errors** (stale cache, network, deploy race) get a targeted
 *   message suggesting the user reload.
 * - **Other render errors** get a generic fallback so the rest of the app
 *   remains functional. Transient DOM-mutation races additionally offer an
 *   in-place retry, since a full page reload is unnecessary for them.
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
    isRetryableError: false,
    retryCount: 0,
  };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    // Only the error flags are reset here;  is intentionally
    // preserved so that a page which keeps failing cannot be retried forever.
    return {
      hasError: true,
      isChunkError: isChunkLoadError(error),
      restarting: false,
      restartError: "",
      isRetryableError: isDomMutationError(error),
    };
  }

  componentDidUpdate(prevProps: Readonly<Props>) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.reset();
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    const label = isChunkLoadError(error)
      ? "Chunk load error"
      : isDomMutationError(error)
      ? "DOM mutation error"
      : "Render error";
    console.error(`${label}:`, error, info);
  }

  private reset = () => {
    this.setState({
      hasError: false,
      isChunkError: false,
      restarting: false,
      restartError: "",
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
      retryCount: prev.retryCount + 1,
    }));
  };

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
            <Space wrap>
              {canRetry && (
                <Button type="primary" onClick={this.retryRender}>
                  {i18n.t("chunkError.retry")}
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
          }
          style={{ marginTop: "10vh" }}
        />
      );
    }
    return this.props.children;
  }
}

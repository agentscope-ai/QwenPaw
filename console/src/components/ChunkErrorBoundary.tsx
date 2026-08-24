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
 * Error boundary that wraps lazily-loaded route chunks.
 *
 * - **Chunk-load errors** (stale cache, network, deploy race) get a targeted
 *   message suggesting the user reload.
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
  };

  static getDerivedStateFromError(error: unknown): State {
    return {
      hasError: true,
      isChunkError: isChunkLoadError(error),
      restarting: false,
      restartError: "",
    };
  }

  componentDidUpdate(prevProps: Readonly<Props>) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({
        hasError: false,
        isChunkError: false,
        restarting: false,
        restartError: "",
      });
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    const label = isChunkLoadError(error) ? "Chunk load error" : "Render error";
    console.error(`${label}:`, error, info);
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
            <Space wrap>
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
          }
          style={{ marginTop: "10vh" }}
        />
      );
    }
    return this.props.children;
  }
}

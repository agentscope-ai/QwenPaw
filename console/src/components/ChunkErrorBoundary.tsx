import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";
import { Button, Result } from "antd";
import i18n from "../i18n";

interface Props {
  children: ReactNode;
  /** When this key changes the error state is automatically cleared. */
  resetKey?: string;
}

interface State {
  hasError: boolean;
  isChunkError: boolean;
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
  state: State = { hasError: false, isChunkError: false };

  static getDerivedStateFromError(error: unknown): State {
    return { hasError: true, isChunkError: isChunkLoadError(error) };
  }

  componentDidUpdate(prevProps: Readonly<Props>) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false, isChunkError: false });
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    const label = isChunkLoadError(error) ? "Chunk load error" : "Render error";
    console.error(`${label}:`, error, info);
  }

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
          subTitle={i18n.t(subTitleKey)}
          extra={
            <Button type="primary" onClick={() => window.location.reload()}>
              {i18n.t("chunkError.reload")}
            </Button>
          }
          style={{ marginTop: "10vh" }}
        />
      );
    }
    return this.props.children;
  }
}

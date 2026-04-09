import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";
import { Button, Result } from "antd";

interface Props {
  children: ReactNode;
  /** When this key changes the error state is automatically cleared. */
  resetKey?: string;
}

interface State {
  hasError: boolean;
}

/**
 * Error boundary for lazy-loaded route chunks.
 *
 * Catches render errors caused by failed dynamic imports (stale cache,
 * network issues, deploy races) and shows a recovery UI with a reload button.
 *
 * Pass a `resetKey` derived from the current route so the boundary
 * automatically recovers when the user navigates to a different page.
 */
export class ChunkErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidUpdate(prevProps: Readonly<Props>) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false });
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Chunk load error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <Result
          status="error"
          title="Failed to load page"
          subTitle="This may be caused by a network issue or an application update."
          extra={
            <Button type="primary" onClick={() => window.location.reload()}>
              Reload
            </Button>
          }
          style={{ marginTop: "10vh" }}
        />
      );
    }
    return this.props.children;
  }
}

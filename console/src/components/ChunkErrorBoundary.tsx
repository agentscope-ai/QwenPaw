import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";
import { Button, Result } from "antd";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

/**
 * Error boundary for lazy-loaded route chunks.
 *
 * Catches render errors caused by failed dynamic imports (stale cache,
 * network issues, deploy races) and shows a recovery UI with a reload button.
 */
export class ChunkErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
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

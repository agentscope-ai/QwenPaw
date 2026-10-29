import { Button } from "@agentscope-ai/design";
import type { ReactNode } from "react";

export interface LoadingStateProps {
  message: string;
  error?: boolean;
  onRetry?: () => void;
  className?: string;
}

/** Shared state markup with the caller's existing colors and density. */
export function LoadingState({
  message,
  error,
  onRetry,
  className,
  textClassName,
  errorColor,
  retryLabel,
}: LoadingStateProps & {
  textClassName?: string;
  errorColor: string;
  retryLabel: ReactNode;
}) {
  return (
    <div className={className}>
      <span
        className={textClassName}
        style={{ color: error ? errorColor : undefined }}
      >
        {message}
      </span>
      {error && onRetry && (
        <Button onClick={onRetry} style={{ marginTop: 12 }}>
          {retryLabel}
        </Button>
      )}
    </div>
  );
}

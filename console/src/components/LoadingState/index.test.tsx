import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LoadingState } from "./index";

describe("shared LoadingState", () => {
  it.each([
    ["var(--app-error-text)", "Retry"],
    ["#ff4d4f", "Refresh"],
  ])(
    "preserves the caller's error color %s and retry label",
    (color, label) => {
      const onRetry = vi.fn();
      const { container } = render(
        <LoadingState
          message="Request failed"
          error
          errorColor={color}
          retryLabel={label}
          onRetry={onRetry}
          className="existing-state"
          textClassName="existing-message"
        />,
      );

      expect(container.firstElementChild).toHaveClass("existing-state");
      const message = screen.getByText("Request failed");
      expect(message).toHaveClass("existing-message");
      expect(message).toHaveStyle({ color });
      const retry = screen.getByRole("button", { name: label });
      expect(retry).toHaveStyle({ marginTop: "12px" });
      fireEvent.click(retry);
      expect(onRetry).toHaveBeenCalledOnce();
    },
  );

  it("does not apply error presentation to the loading state", () => {
    render(
      <LoadingState
        message="Loading"
        errorColor="#ff4d4f"
        retryLabel="Retry"
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("Loading")).not.toHaveAttribute("style");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("does not show a retry action without a handler", () => {
    render(
      <LoadingState
        message="Request failed"
        error
        errorColor="var(--app-error-text)"
        retryLabel="Retry"
      />,
    );

    expect(screen.getByText("Request failed")).toHaveStyle({
      color: "var(--app-error-text)",
    });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

// @vitest-environment jsdom
import { fireEvent, render, screen, within } from "@testing-library/react";
import { cloneElement } from "react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactElement,
  ReactNode,
} from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MessageQueuePanel, { type QueueItem } from "./MessageQueuePanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@agentscope-ai/design", () => ({
  IconButton: ({
    icon,
    iconSize,
    size,
    onClick,
  }: ButtonHTMLAttributes<HTMLButtonElement> & {
    icon?: ReactElement<{ size?: string | number }>;
    iconSize?: number;
    size?: string;
  }) => (
    <button onClick={onClick}>
      {/* Spark forwards iconSize or the button size to its icon. */}
      {icon && cloneElement(icon, { size: iconSize ?? size })}
    </button>
  ),
}));

vi.mock("antd", () => ({
  Input: (props: InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
  Tooltip: ({ children, title }: { children: ReactNode; title: string }) => (
    <span title={title}>{children}</span>
  ),
}));

const item = (status: QueueItem["status"]): QueueItem => ({
  id: status,
  text: `${status} item`,
  status,
  retryCount: 0,
  createdAt: 1,
});

const handlers = {
  onRemove: vi.fn(),
  onEdit: vi.fn(),
  onReorder: vi.fn(),
  onInterruptAndSend: vi.fn(),
  onClear: vi.fn(),
  onPauseResume: vi.fn(),
  onRetry: vi.fn(),
  onSkip: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("MessageQueuePanel icons", () => {
  it.each(["running", "paused", "error"] as const)(
    "renders valid SVG dimensions while %s",
    (runState) => {
      const { container } = render(
        <MessageQueuePanel
          {...handlers}
          items={[item("pending"), item("failed")]}
          runState={runState}
        />,
      );

      const icons = container.querySelectorAll("button svg");
      expect(icons).toHaveLength(10);
      for (const icon of icons) {
        expect(Number(icon.getAttribute("width"))).toBeGreaterThan(0);
        expect(Number(icon.getAttribute("height"))).toBeGreaterThan(0);
      }
    },
  );

  it("keeps embedded row actions working with numeric icon sizes", () => {
    const queuedItem = item("pending");
    const { container } = render(
      <MessageQueuePanel
        {...handlers}
        embedded
        items={[queuedItem]}
        runState="running"
      />,
    );

    const icons = container.querySelectorAll("button svg");
    expect(icons).toHaveLength(3);
    for (const icon of icons) {
      expect(icon).toHaveAttribute("width", "13");
      expect(icon).toHaveAttribute("height", "13");
    }

    fireEvent.click(
      within(screen.getByTitle("chat.queue.interruptAndSend")).getByRole(
        "button",
      ),
    );
    expect(handlers.onInterruptAndSend).toHaveBeenCalledWith(queuedItem);

    fireEvent.click(
      within(screen.getByTitle("chat.queue.delete")).getByRole("button"),
    );
    expect(handlers.onRemove).toHaveBeenCalledWith(queuedItem.id);

    fireEvent.click(
      within(screen.getByTitle("chat.queue.edit")).getByRole("button"),
    );
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Updated queued message" } });
    fireEvent.blur(input);
    expect(handlers.onEdit).toHaveBeenCalledWith(
      queuedItem.id,
      "Updated queued message",
    );
  });

  it("keeps failed item retry and skip actions working", () => {
    const failedItem = item("failed");
    render(
      <MessageQueuePanel
        {...handlers}
        embedded
        items={[failedItem]}
        runState="error"
      />,
    );

    fireEvent.click(
      within(screen.getByTitle("chat.queue.retry")).getByRole("button"),
    );
    expect(handlers.onRetry).toHaveBeenCalledWith(failedItem.id);

    fireEvent.click(
      within(screen.getByTitle("chat.queue.skip")).getByRole("button"),
    );
    expect(handlers.onSkip).toHaveBeenCalledWith(failedItem.id);
  });
});

describe("MessageQueuePanel theme tokens", () => {
  it("uses semantic status tokens for paused, error and sending states", () => {
    const view = render(
      <MessageQueuePanel
        {...handlers}
        items={[item("sending")]}
        runState="paused"
      />,
    );

    expect(screen.getByText("chat.queue.paused")).toHaveStyle({
      color: "var(--app-warning-text)",
    });
    expect(screen.getByText("sending item")).toHaveStyle({
      color: "var(--app-accent-text)",
    });

    view.rerender(
      <div className="dark-mode">
        <MessageQueuePanel
          {...handlers}
          items={[item("failed")]}
          runState="error"
        />
      </div>,
    );

    expect(screen.getByText("chat.queue.sendFailed")).toHaveStyle({
      color: "var(--app-error-text)",
    });
    expect(screen.getByText("failed item")).toHaveStyle({
      color: "var(--app-error-text)",
    });
  });
});

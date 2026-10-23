// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
} from "react";
import { describe, expect, it, vi } from "vitest";
import MessageQueuePanel, { type QueueItem } from "./MessageQueuePanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@agentscope-ai/design", () => ({
  IconButton: ({
    icon,
    ...props
  }: ButtonHTMLAttributes<HTMLButtonElement> & { icon?: ReactNode }) => (
    <button {...props}>{icon}</button>
  ),
}));

vi.mock("antd", () => ({
  Input: (props: InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
  Tooltip: ({ children }: { children: ReactNode }) => children,
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

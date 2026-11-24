// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import ApprovalQueueOverlay from "./ApprovalQueueOverlay";

vi.mock("@agentscope-ai/design", () => ({
  IconButton: ({
    icon,
    ...props
  }: ButtonHTMLAttributes<HTMLButtonElement> & { icon?: ReactNode }) => (
    <button {...props}>{icon}</button>
  ),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { current?: number; total?: number }) =>
      ({
        "approval.queue.title": "Pending approvals",
        "approval.queue.previous": "Previous approval",
        "approval.queue.next": "Next approval",
      })[key] ?? `${values?.current} / ${values?.total}`,
  }),
}));

const requests = [
  { requestId: "first", label: "First approval" },
  { requestId: "second", label: "Second approval" },
];

describe("ApprovalQueueOverlay", () => {
  it("shows one discoverable approval at a time with N/M navigation", async () => {
    const user = userEvent.setup();
    render(
      <ApprovalQueueOverlay
        items={requests}
        renderItem={(item) => (
          <button type="button">Resolve {item.label}</button>
        )}
      />,
    );

    expect(
      screen.getByRole("region", { name: "Pending approvals" }),
    ).toBeTruthy();
    expect(screen.getByText("1 / 2")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Resolve First approval" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Resolve Second approval" }),
    ).toBeNull();

    await user.tab();
    expect(screen.getByRole("button", { name: "Next approval" })).toHaveFocus();
    await user.tab();
    expect(
      screen.getByRole("button", { name: "Resolve First approval" }),
    ).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Next approval" }));
    expect(screen.getByText("2 / 2")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Resolve Second approval" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Resolve First approval" }),
    ).toBeNull();
  });

  it("keeps the queue position when a middle approval resolves", async () => {
    const user = userEvent.setup();
    const triple = [
      { requestId: "first", label: "First approval" },
      { requestId: "second", label: "Second approval" },
      { requestId: "third", label: "Third approval" },
    ];

    function Harness() {
      const [items, setItems] = useState(triple);
      return (
        <ApprovalQueueOverlay
          items={items}
          renderItem={(item) => (
            <button
              type="button"
              onClick={() =>
                setItems((current) =>
                  current.filter(
                    (candidate) => candidate.requestId !== item.requestId,
                  ),
                )
              }
            >
              Resolve {item.label}
            </button>
          )}
        />
      );
    }

    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Next approval" }));
    expect(screen.getByText("2 / 3")).toBeTruthy();

    await user.click(
      screen.getByRole("button", { name: "Resolve Second approval" }),
    );

    // Position 2 of the remaining two cards is the third approval, not a
    // rewind to the first one.
    expect(screen.getByText("2 / 2")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Resolve Third approval" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Resolve First approval" }),
    ).toBeNull();
  });

  it("advances after resolving the current approval without activating the next", async () => {
    const user = userEvent.setup();
    const resolved = vi.fn();

    function Harness() {
      const [items, setItems] = useState(requests);
      return (
        <ApprovalQueueOverlay
          items={items}
          renderItem={(item) => (
            <button
              type="button"
              onClick={() => {
                resolved(item.requestId);
                setItems((current) =>
                  current.filter(
                    (candidate) => candidate.requestId !== item.requestId,
                  ),
                );
              }}
            >
              Resolve {item.label}
            </button>
          )}
        />
      );
    }

    render(<Harness />);
    await user.click(
      screen.getByRole("button", { name: "Resolve First approval" }),
    );

    expect(resolved).toHaveBeenCalledTimes(1);
    expect(resolved).toHaveBeenCalledWith("first");
    expect(screen.getByText("1 / 1")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Resolve Second approval" }),
    ).toBeTruthy();
  });

  it("selects and focuses the approval targeted by a notification", async () => {
    render(
      <ApprovalQueueOverlay
        items={requests}
        focusedRequestId="second"
        focusKey="notification-1"
        renderItem={(item) => <span>{item.label}</span>}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Second approval")).toBeInTheDocument();
      expect(screen.queryByText("First approval")).toBeNull();
      expect(
        document.querySelector('[data-approval-id="second"]'),
      ).toHaveFocus();
    });
  });
});

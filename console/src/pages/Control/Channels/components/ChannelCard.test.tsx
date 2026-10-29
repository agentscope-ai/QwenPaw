// @vitest-environment jsdom
import type { ComponentProps, KeyboardEvent, ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const capturedCardProps = vi.hoisted<{
  value: Record<string, unknown> | null;
}>(() => ({ value: null }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? _key,
  }),
}));

vi.mock("@/components/interaction/InteractiveCard", () => ({
  InteractiveCard: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));

vi.mock("@agentscope-ai/design", () => ({
  Card: ({
    children,
    onClick,
    onKeyDown,
    ...props
  }: ComponentProps<"article"> & {
    children?: ReactNode;
    onKeyDown?: (event: KeyboardEvent<HTMLElement>) => void;
    styles?: { body?: { padding?: number } };
  }) => {
    capturedCardProps.value = props;
    return (
      <article onClick={onClick} onKeyDown={onKeyDown} {...props}>
        {children}
      </article>
    );
  },
}));

vi.mock("./ChannelIcon", () => ({
  ChannelIcon: () => <span aria-hidden="true" />,
}));

import { ChannelCard } from "./ChannelCard";

beforeEach(() => {
  capturedCardProps.value = null;
});

describe("ChannelCard", () => {
  it("keeps the body padding and accessible name", () => {
    render(<ChannelCard channelKey="console" config={{}} onClick={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Console" })).toBeTruthy();
    expect(capturedCardProps.value).toEqual(
      expect.objectContaining({ styles: { body: { padding: 24 } } }),
    );
    expect(capturedCardProps.value).not.toHaveProperty("bodyStyle");
  });

  it.each(["click", "Enter", " "])("activates once for %s", (interaction) => {
    const onClick = vi.fn();
    render(<ChannelCard channelKey="console" config={{}} onClick={onClick} />);
    const card = screen.getByRole("button", { name: "Console" });

    if (interaction === "click") {
      fireEvent.click(card);
    } else {
      fireEvent.keyDown(card, { key: interaction });
    }

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ChannelDependencyStatus } from "../../../../api/modules/channel";
import { ChannelAvailableItem } from "./ChannelAvailableItem";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("./ChannelIcon", () => ({
  ChannelIcon: () => <span data-testid="channel-icon" />,
}));

function status(
  name: "missing" | "failed" | "installing" | "load_error",
): ChannelDependencyStatus {
  return {
    channel: "telegram",
    status: name,
    requirements: ["python-telegram-bot>=20.0"],
    missing_requirements: ["python-telegram-bot>=20.0"],
  };
}

describe("ChannelAvailableItem", () => {
  it.each([
    ["checking", "channels.dependencyCheckingAction"],
    ["failed", "channels.dependencyCheckFailedAction"],
  ] as const)("disables the dependency check %s state", (name, label) => {
    const onClick = vi.fn();
    render(
      <ChannelAvailableItem
        channelKey="telegram"
        dependencyCheckState={name}
        onClick={onClick}
      />,
    );

    const item = screen.getByRole("button");
    fireEvent.click(item);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(item).toHaveAttribute("aria-disabled", "true");
    expect(onClick).not.toHaveBeenCalled();
  });

  it("shows install and remains clickable when dependencies are missing", () => {
    const onClick = vi.fn();
    render(
      <ChannelAvailableItem
        channelKey="telegram"
        dependencyStatus={status("missing")}
        onClick={onClick}
      />,
    );

    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("channels.installAction")).toBeInTheDocument();
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("shows retry after an installation failure", () => {
    render(
      <ChannelAvailableItem
        channelKey="telegram"
        dependencyStatus={status("failed")}
        onClick={vi.fn()}
      />,
    );
    expect(screen.getByText("channels.retryInstallAction")).toBeInTheDocument();
  });

  it.each([
    ["installing", "channels.installingAction"],
    ["load_error", "channels.loadFailedAction"],
  ] as const)("disables the %s state", (name, label) => {
    const onClick = vi.fn();
    render(
      <ChannelAvailableItem
        channelKey="telegram"
        dependencyStatus={status(name)}
        onClick={onClick}
      />,
    );

    const item = screen.getByRole("button");
    fireEvent.click(item);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(item).toHaveAttribute("aria-disabled", "true");
    expect(onClick).not.toHaveBeenCalled();
  });
});

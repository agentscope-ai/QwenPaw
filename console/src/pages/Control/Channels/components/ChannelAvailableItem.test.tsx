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

  it("keeps the installing state clickable so it can be stopped", () => {
    const onClick = vi.fn();
    render(
      <ChannelAvailableItem
        channelKey="telegram"
        dependencyStatus={status("installing")}
        onClick={onClick}
      />,
    );

    const item = screen.getByRole("button");
    fireEvent.click(item);
    expect(screen.getByText("channels.installingAction")).toBeInTheDocument();
    expect(item).toHaveAttribute("aria-disabled", "false");
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("offers reinstall when the channel fails to load", () => {
    const onClick = vi.fn();
    render(
      <ChannelAvailableItem
        channelKey="telegram"
        dependencyStatus={status("load_error")}
        onClick={onClick}
      />,
    );

    const item = screen.getByRole("button");
    fireEvent.click(item);
    expect(screen.getByText("channels.reinstallAction")).toBeInTheDocument();
    expect(item).toHaveAttribute("aria-disabled", "false");
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("keeps a core-only load error disabled", () => {
    const onClick = vi.fn();
    const loadError = status("load_error");
    loadError.requirements = [];
    render(
      <ChannelAvailableItem
        channelKey="telegram"
        dependencyStatus={loadError}
        onClick={onClick}
      />,
    );

    const item = screen.getByRole("button");
    fireEvent.click(item);
    expect(screen.getByText("channels.loadFailedAction")).toBeInTheDocument();
    expect(item).toHaveAttribute("aria-disabled", "true");
    expect(onClick).not.toHaveBeenCalled();
  });
});

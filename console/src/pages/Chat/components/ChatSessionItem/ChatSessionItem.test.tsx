import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import ChatSessionItem from "./index";

vi.mock("@agentscope-ai/design", () => ({
  IconButton: ({
    onClick,
    icon,
  }: {
    onClick?: (e: React.MouseEvent) => void;
    icon: React.ReactNode;
  }) => <button onClick={onClick}>{icon}</button>,
}));

// mock getChannelIconUrl and ChannelIcon to avoid network requests
vi.mock("../../../Control/Channels/components", () => ({
  getChannelIconUrl: (key: string) => `/icons/${key}.png`,
  ChannelIcon: ({
    channelKey,
    size,
  }: {
    channelKey: string;
    size?: number;
  }) => (
    <img
      src={`/icons/${channelKey}.png`}
      alt={channelKey}
      width={size}
      height={size}
    />
  ),
}));

const baseProps = {
  name: "Test Session",
  time: "2024-01-01 12:00:00",
};

describe("ChatSessionItem", () => {
  it("renders session name and time", () => {
    renderWithProviders(<ChatSessionItem {...baseProps} />);
    expect(screen.getByText("Test Session")).toBeInTheDocument();
    expect(screen.getByText("2024-01-01 12:00:00")).toBeInTheDocument();
  });

  it("clicking the item triggers onClick callback", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    renderWithProviders(<ChatSessionItem {...baseProps} onClick={onClick} />);
    await user.click(screen.getByText("Test Session"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("clicking edit button triggers onEdit and does not bubble to onClick", () => {
    // action buttons are hidden via CSS (pointer-events:none until hover), use fireEvent
    const onClick = vi.fn();
    const onEdit = vi.fn();
    renderWithProviders(
      <ChatSessionItem {...baseProps} onClick={onClick} onEdit={onEdit} />,
    );
    fireEvent.click(
      document.querySelector('[data-icon="SparkEditLine"]')!.closest("button")!,
    );
    expect(onEdit).toHaveBeenCalledOnce();
    expect(onClick).not.toHaveBeenCalled();
  });

  it("clicking delete button triggers onDelete and does not bubble to onClick", () => {
    const onClick = vi.fn();
    const onDelete = vi.fn();
    renderWithProviders(
      <ChatSessionItem {...baseProps} onClick={onClick} onDelete={onDelete} />,
    );
    fireEvent.click(
      document
        .querySelector('[data-icon="SparkDeleteLine"]')!
        .closest("button")!,
    );
    expect(onDelete).toHaveBeenCalledOnce();
    expect(onClick).not.toHaveBeenCalled();
  });

  it("editing mode shows Input instead of name text", () => {
    renderWithProviders(
      <ChatSessionItem {...baseProps} editing editValue="edit text" />,
    );
    expect(screen.queryByText("Test Session")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("typing in editing mode triggers onEditChange", async () => {
    const user = userEvent.setup();
    const onEditChange = vi.fn();
    renderWithProviders(
      <ChatSessionItem
        {...baseProps}
        editing
        editValue=""
        onEditChange={onEditChange}
      />,
    );
    await user.type(screen.getByRole("textbox"), "new name");
    expect(onEditChange).toHaveBeenCalled();
  });

  it("clicking item in editing mode does not trigger onClick", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    renderWithProviders(
      <ChatSessionItem
        {...baseProps}
        editing
        editValue="x"
        onClick={onClick}
      />,
    );
    await user.click(screen.getByRole("textbox"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("shows channel label when channelLabel is provided", () => {
    renderWithProviders(
      <ChatSessionItem
        {...baseProps}
        channelKey="dingtalk"
        channelLabel="DingTalk"
      />,
    );
    expect(screen.getByText("DingTalk")).toBeInTheDocument();
  });

  it("does not show channel area when channelLabel is not provided", () => {
    renderWithProviders(<ChatSessionItem {...baseProps} />);
    expect(screen.queryByTitle(/.*/)).not.toBeInTheDocument();
  });
});

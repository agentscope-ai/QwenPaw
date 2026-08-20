import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import ThinkingLevelToggle from "./ThinkingLevelToggle";

const messageMock = vi.hoisted(() => ({
  error: vi.fn(),
}));

const sessionApiMock = vi.hoisted(() => ({
  getSessionList: vi.fn(),
  getSessionMeta: vi.fn(),
  updateSessionMeta: vi.fn(),
}));

vi.mock("../sessionApi", () => ({ default: sessionApiMock }));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: messageMock }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("ThinkingLevelToggle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionApiMock.getSessionList.mockResolvedValue([]);
    sessionApiMock.getSessionMeta.mockReturnValue({ thinking_level: "high" });
    sessionApiMock.updateSessionMeta.mockResolvedValue(undefined);
  });

  it("loads the Session level and persists a new selection", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <ThinkingLevelToggle
        sessionId="chat-1"
        supportsThinking
        onChange={onChange}
      />,
    );

    await waitFor(() =>
      expect(sessionApiMock.getSessionList).toHaveBeenCalled(),
    );
    const trigger = await screen.findByLabelText("chat.thinkingLevelTitle");
    expect(trigger).toHaveTextContent("modelSelector.thinking.high");
    await user.click(trigger);
    const selectedItem = screen.getByRole("menuitem", {
      name: "modelSelector.thinking.high",
    });
    const selectedContent = within(selectedItem).getByText(
      "modelSelector.thinking.high",
    ).parentElement;
    expect(selectedContent?.lastElementChild).toHaveClass("lucide-check");

    await user.click(
      screen.getByRole("menuitem", { name: "modelSelector.thinking.low" }),
    );

    expect(sessionApiMock.updateSessionMeta).toHaveBeenCalledWith("chat-1", {
      thinking_level: "low",
    });
    expect(onChange).toHaveBeenLastCalledWith("low");
  });

  it("hides the selector for models without thinking support", async () => {
    renderWithProviders(
      <ThinkingLevelToggle sessionId="chat-1" supportsThinking={false} />,
    );
    await waitFor(() =>
      expect(sessionApiMock.getSessionList).toHaveBeenCalled(),
    );

    expect(
      screen.queryByLabelText("chat.thinkingLevelTitle"),
    ).not.toBeInTheDocument();
  });

  it("restores the previous level and reports a persistence failure", async () => {
    sessionApiMock.updateSessionMeta.mockRejectedValueOnce(
      new Error("保存失败"),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <ThinkingLevelToggle sessionId="chat-1" supportsThinking />,
    );

    const trigger = await screen.findByLabelText("chat.thinkingLevelTitle");
    await user.click(trigger);
    await user.click(
      screen.getByRole("menuitem", { name: "modelSelector.thinking.low" }),
    );

    await waitFor(() =>
      expect(messageMock.error).toHaveBeenCalledWith("保存失败"),
    );
    expect(trigger).toHaveTextContent("modelSelector.thinking.high");
  });
});

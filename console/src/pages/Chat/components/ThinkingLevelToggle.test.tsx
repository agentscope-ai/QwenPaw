import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import ThinkingLevelToggle from "./ThinkingLevelToggle";

const sessionApiMock = vi.hoisted(() => ({
  getSessionList: vi.fn(),
  getSessionMeta: vi.fn(),
  updateSessionMeta: vi.fn(),
}));

vi.mock("../sessionApi", () => ({ default: sessionApiMock }));

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
      <ThinkingLevelToggle sessionId="chat-1" onChange={onChange} />,
    );

    await waitFor(() =>
      expect(sessionApiMock.getSessionList).toHaveBeenCalled(),
    );
    act(() => {
      window.dispatchEvent(
        new CustomEvent("model-thinking-support-changed", {
          detail: { supportsThinking: true },
        }),
      );
    });

    const trigger = await screen.findByLabelText("chat.thinkingLevelTitle");
    expect(trigger).toHaveTextContent("modelSelector.thinking.high");
    await user.click(trigger);
    await user.click(await screen.findByText("modelSelector.thinking.low"));

    expect(sessionApiMock.updateSessionMeta).toHaveBeenCalledWith("chat-1", {
      thinking_level: "low",
    });
    expect(onChange).toHaveBeenLastCalledWith("low");
  });

  it("hides the selector for models without thinking support", async () => {
    renderWithProviders(<ThinkingLevelToggle sessionId="chat-1" />);
    await waitFor(() =>
      expect(sessionApiMock.getSessionList).toHaveBeenCalled(),
    );

    act(() => {
      window.dispatchEvent(
        new CustomEvent("model-thinking-support-changed", {
          detail: { supportsThinking: false },
        }),
      );
    });

    expect(
      screen.queryByLabelText("chat.thinkingLevelTitle"),
    ).not.toBeInTheDocument();
  });
});

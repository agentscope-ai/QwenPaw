import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useCommandSuggestions } from "./useChatInput";
import type { CommandSuggestion } from "../types";

const mockCommands: CommandSuggestion[] = [
  { command: "/clear", value: "clear", description: "Clear history" },
  { command: "/compact", value: "compact", description: "Compact mode" },
  { command: "/help", value: "help", description: "Show help" },
];

describe("useCommandSuggestions", () => {
  it("initial state is not visible with no suggestions", () => {
    const { result } = renderHook(() =>
      useCommandSuggestions({ commands: mockCommands }),
    );
    expect(result.current.visible).toBe(false);
    expect(result.current.suggestions).toEqual([]);
  });

  it("shows suggestions when input starts with /", () => {
    const { result } = renderHook(() =>
      useCommandSuggestions({ commands: mockCommands }),
    );
    act(() => {
      result.current.handleInputChange("/");
    });
    expect(result.current.visible).toBe(true);
    expect(result.current.suggestions).toHaveLength(3);
  });

  it("filters commands by prefix", () => {
    const { result } = renderHook(() =>
      useCommandSuggestions({ commands: mockCommands }),
    );
    act(() => {
      result.current.handleInputChange("/cl");
    });
    expect(result.current.suggestions).toHaveLength(1);
    expect(result.current.suggestions[0].command).toBe("/clear");
  });

  it("hides suggestions when input does not start with /", () => {
    const { result } = renderHook(() =>
      useCommandSuggestions({ commands: mockCommands }),
    );
    act(() => {
      result.current.handleInputChange("/cl");
    });
    expect(result.current.visible).toBe(true);

    act(() => {
      result.current.handleInputChange("hello");
    });
    expect(result.current.visible).toBe(false);
    expect(result.current.suggestions).toEqual([]);
  });

  it("selectCommand returns the command value and hides suggestions", () => {
    const { result } = renderHook(() =>
      useCommandSuggestions({ commands: mockCommands }),
    );
    act(() => {
      result.current.handleInputChange("/cl");
    });

    let selectedValue: string = "";
    act(() => {
      selectedValue = result.current.selectCommand(mockCommands[0]);
    });
    expect(selectedValue).toBe("clear");
    expect(result.current.visible).toBe(false);
  });

  it("dismiss hides suggestions", () => {
    const { result } = renderHook(() =>
      useCommandSuggestions({ commands: mockCommands }),
    );
    act(() => {
      result.current.handleInputChange("/");
    });
    expect(result.current.visible).toBe(true);

    act(() => {
      result.current.dismiss();
    });
    expect(result.current.visible).toBe(false);
  });

  it("case-insensitive filtering", () => {
    const { result } = renderHook(() =>
      useCommandSuggestions({ commands: mockCommands }),
    );
    act(() => {
      result.current.handleInputChange("/CL");
    });
    expect(result.current.suggestions).toHaveLength(1);
    expect(result.current.suggestions[0].command).toBe("/clear");
  });

  it("returns empty suggestions when no match", () => {
    const { result } = renderHook(() =>
      useCommandSuggestions({ commands: mockCommands }),
    );
    act(() => {
      result.current.handleInputChange("/xyz");
    });
    expect(result.current.visible).toBe(true);
    expect(result.current.suggestions).toEqual([]);
  });
});

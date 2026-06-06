import { useCallback, useEffect, useRef, useState } from "react";
import type { CommandSuggestion } from "../types";

// ---------------------------------------------------------------------------
// IME Composition handling
// ---------------------------------------------------------------------------

export function useIMEComposition() {
  const isComposingRef = useRef(false);

  useEffect(() => {
    const handleStart = () => {
      isComposingRef.current = true;
    };
    const handleEnd = () => {
      // Small delay for Safari compositionend timing
      setTimeout(() => {
        isComposingRef.current = false;
      }, 50);
    };

    document.addEventListener("compositionstart", handleStart, true);
    document.addEventListener("compositionend", handleEnd, true);
    return () => {
      document.removeEventListener("compositionstart", handleStart, true);
      document.removeEventListener("compositionend", handleEnd, true);
    };
  }, []);

  return isComposingRef;
}

// ---------------------------------------------------------------------------
// Message History Navigation (ArrowUp/Down to cycle through sent messages)
// ---------------------------------------------------------------------------

export interface UseMessageHistoryOptions {
  getUserMessages: () => string[];
  textareaSelector?: string;
}

export function useMessageHistory({
  getUserMessages,
  textareaSelector = 'textarea[class*="sender"], textarea[data-chat-input]',
}: UseMessageHistoryOptions) {
  const historyIndexRef = useRef(-1);
  const draftRef = useRef("");
  const isComposingRef = useIMEComposition();

  const setTextareaValue = useCallback(
    (textarea: HTMLTextAreaElement, value: string) => {
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      if (nativeInputValueSetter) {
        nativeInputValueSetter.call(textarea, value);
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
      }
    },
    [],
  );

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;

      const target = e.target as HTMLElement;
      if (target?.tagName !== "TEXTAREA") return;
      if (!target.matches(textareaSelector)) return;
      if (
        isComposingRef.current ||
        (e as unknown as { isComposing: boolean }).isComposing
      )
        return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      const textarea = target as HTMLTextAreaElement;
      if (textarea.selectionStart !== textarea.selectionEnd) return;

      const userMessages = getUserMessages();
      if (userMessages.length === 0) return;

      if (e.key === "ArrowUp") {
        // Don't intercept if cursor is not on first line
        const textBefore = textarea.value.substring(
          0,
          textarea.selectionStart || 0,
        );
        if (textBefore.includes("\n")) return;

        // Don't intercept if command suggestions are showing
        if (textarea.value.startsWith("/")) return;

        if (historyIndexRef.current === -1) {
          draftRef.current = textarea.value;
        }

        const nextIndex = historyIndexRef.current + 1;
        if (nextIndex < userMessages.length) {
          e.preventDefault();
          historyIndexRef.current = nextIndex;
          setTextareaValue(
            textarea,
            userMessages[userMessages.length - 1 - nextIndex],
          );
        }
      } else if (e.key === "ArrowDown") {
        if (historyIndexRef.current < 0) return;

        // Don't intercept if cursor is not on last line
        const textAfter = textarea.value.substring(
          textarea.selectionStart || 0,
        );
        if (textAfter.includes("\n")) return;

        const nextIndex = historyIndexRef.current - 1;
        if (nextIndex >= 0) {
          e.preventDefault();
          historyIndexRef.current = nextIndex;
          setTextareaValue(
            textarea,
            userMessages[userMessages.length - 1 - nextIndex],
          );
        } else {
          e.preventDefault();
          historyIndexRef.current = -1;
          setTextareaValue(textarea, draftRef.current);
        }
      }
    };

    const handleFocus = () => {
      historyIndexRef.current = -1;
      draftRef.current = "";
    };

    document.addEventListener("keydown", handleKeyDown, true);
    document.addEventListener("focusin", handleFocus, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      document.removeEventListener("focusin", handleFocus, true);
    };
  }, [getUserMessages, textareaSelector, setTextareaValue, isComposingRef]);
}

// ---------------------------------------------------------------------------
// Command Suggestions (/slash commands)
// ---------------------------------------------------------------------------

export interface UseCommandSuggestionsOptions {
  commands: CommandSuggestion[];
}

export function useCommandSuggestions({
  commands,
}: UseCommandSuggestionsOptions) {
  const [query, setQuery] = useState("");
  const [visible, setVisible] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const filteredCommands = commands.filter((cmd) =>
    cmd.command.toLowerCase().startsWith(`/${query.toLowerCase()}`),
  );

  const suggestions = visible ? filteredCommands : [];

  const handleInputChange = useCallback((value: string) => {
    if (value.startsWith("/")) {
      setQuery(value.slice(1));
      setVisible(true);
      setActiveIndex(-1);
    } else {
      setVisible(false);
      setQuery("");
      setActiveIndex(-1);
    }
  }, []);

  const selectCommand = useCallback((command: CommandSuggestion) => {
    setVisible(false);
    setQuery("");
    setActiveIndex(-1);
    return command.value;
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent): CommandSuggestion | null => {
      if (!visible || suggestions.length === 0) return null;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((prev) =>
          prev < suggestions.length - 1 ? prev + 1 : 0,
        );
        return null;
      }

      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((prev) =>
          prev > 0 ? prev - 1 : suggestions.length - 1,
        );
        return null;
      }

      if (e.key === "Enter" && activeIndex >= 0 && !e.shiftKey) {
        e.preventDefault();
        const selected = suggestions[activeIndex];
        return selected;
      }

      if (e.key === "Escape") {
        e.preventDefault();
        setVisible(false);
        setActiveIndex(-1);
        return null;
      }

      return null;
    },
    [visible, suggestions, activeIndex],
  );

  return {
    suggestions,
    visible,
    activeIndex,
    handleInputChange,
    selectCommand,
    handleKeyDown,
    dismiss: () => {
      setVisible(false);
      setActiveIndex(-1);
    },
  };
}

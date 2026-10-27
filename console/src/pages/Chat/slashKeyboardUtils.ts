/**
 * slashKeyboardUtils.ts — extracted keyboard logic for slash suggestions (#3274)
 *
 * These pure functions encapsulate the keyboard-event decision logic used in
 * Chat/index.tsx so they can be unit-tested without mounting the full component.
 */

/**
 * Returns true when the slash-suggestion popup should be considered open.
 * The popup is open when the textarea value starts with "/" and contains
 * no whitespace after the slash (i.e. the user is still typing the command).
 */
export function isSuggestionPopupOpen(value: string): boolean {
  return value.startsWith("/") && !/\s/.test(value.slice(1));
}

/**
 * Determines whether ArrowUp / ArrowDown should be intercepted by the
 * slash-suggestion popup instead of triggering message-history navigation.
 *
 * Returns true when the popup is open → caller should NOT navigate history.
 */
export function shouldPopupHandleArrowKey(
  textareaValue: string,
  cursorPosition: number,
): boolean {
  if (!isSuggestionPopupOpen(textareaValue)) return false;
  // When the popup is open and cursor is on the first line, the popup
  // handles arrow keys for navigating the suggestion list.
  const textBeforeCursor = textareaValue.substring(0, cursorPosition);
  const lineBreaks = textBeforeCursor.split("\n").length - 1;
  return lineBreaks === 0;
}

/**
 * Determines whether a Tab keypress should complete the selected slash
 * suggestion. Tab completion only fires when:
 *   1. The suggestion popup is open
 *   2. A suggestion item is highlighted (selectedItem is non-null)
 *   3. The selected item has a data-path-key attribute
 */
export function shouldTabCompleteSuggestion(
  textareaValue: string,
  selectedItem: { getAttribute: (attr: string) => string | null } | null,
): { shouldComplete: boolean; completionText?: string } {
  if (!isSuggestionPopupOpen(textareaValue)) {
    return { shouldComplete: false };
  }
  if (!selectedItem) {
    return { shouldComplete: false };
  }
  const selectedValue = selectedItem.getAttribute("data-path-key")?.trim();
  if (!selectedValue) {
    return { shouldComplete: false };
  }
  return { shouldComplete: true, completionText: `/${selectedValue} ` };
}

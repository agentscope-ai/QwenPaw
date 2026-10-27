import { describe, it, expect } from "vitest";
import {
  isSuggestionPopupOpen,
  shouldPopupHandleArrowKey,
  shouldTabCompleteSuggestion,
} from "./slashKeyboardUtils";

describe("slash suggestion keyboard events (#3274)", () => {
  // ---------------------------------------------------------------------------
  // isSuggestionPopupOpen
  // ---------------------------------------------------------------------------
  describe("isSuggestionPopupOpen", () => {
    it("returns true when value starts with / and no space after", () => {
      expect(isSuggestionPopupOpen("/goal")).toBe(true);
      expect(isSuggestionPopupOpen("/")).toBe(true);
      expect(isSuggestionPopupOpen("/omp")).toBe(true);
    });

    it("returns false when value contains space after /", () => {
      expect(isSuggestionPopupOpen("/goal ")).toBe(false);
      expect(isSuggestionPopupOpen("/omp task")).toBe(false);
    });

    it("returns false when value does not start with /", () => {
      expect(isSuggestionPopupOpen("hello")).toBe(false);
      expect(isSuggestionPopupOpen("")).toBe(false);
      expect(isSuggestionPopupOpen(" /goal")).toBe(false);
    });

    it("returns false for / followed by newline", () => {
      expect(isSuggestionPopupOpen("/\n")).toBe(false);
    });
  });

  // ---------------------------------------------------------------------------
  // shouldPopupHandleArrowKey
  // ---------------------------------------------------------------------------
  describe("shouldPopupHandleArrowKey", () => {
    it("returns true when popup is open and cursor on first line", () => {
      expect(shouldPopupHandleArrowKey("/go", 3)).toBe(true);
      expect(shouldPopupHandleArrowKey("/omp", 4)).toBe(true);
      expect(shouldPopupHandleArrowKey("/", 1)).toBe(true);
    });

    it("returns false when popup is not open (space after command)", () => {
      // User typed "/goal " — popup closed, arrow keys should navigate history
      expect(shouldPopupHandleArrowKey("/goal something", 15)).toBe(false);
    });

    it("returns false when cursor is on a subsequent line", () => {
      // Multi-line input: cursor after newline → history navigation
      expect(shouldPopupHandleArrowKey("/goal\nmore text", 14)).toBe(false);
    });

    it("returns false for non-slash input", () => {
      expect(shouldPopupHandleArrowKey("hello world", 5)).toBe(false);
    });
  });

  // ---------------------------------------------------------------------------
  // shouldTabCompleteSuggestion
  // ---------------------------------------------------------------------------
  describe("shouldTabCompleteSuggestion", () => {
    const makeSelectedItem = (value: string) => ({
      getAttribute: (attr: string) => (attr === "data-path-key" ? value : null),
    });

    it("completes when popup open and item selected", () => {
      const result = shouldTabCompleteSuggestion(
        "/go",
        makeSelectedItem("goal"),
      );
      expect(result.shouldComplete).toBe(true);
      expect(result.completionText).toBe("/goal ");
    });

    it("does not complete when popup is closed", () => {
      const result = shouldTabCompleteSuggestion(
        "/goal something",
        makeSelectedItem("goal"),
      );
      expect(result.shouldComplete).toBe(false);
    });

    it("does not complete when no item is highlighted", () => {
      const result = shouldTabCompleteSuggestion("/go", null);
      expect(result.shouldComplete).toBe(false);
    });

    it("does not complete when selected item has empty data-path-key", () => {
      const result = shouldTabCompleteSuggestion("/go", makeSelectedItem(""));
      expect(result.shouldComplete).toBe(false);
    });

    it("does not complete when data-path-key is whitespace only", () => {
      const result = shouldTabCompleteSuggestion(
        "/go",
        makeSelectedItem("   "),
      );
      expect(result.shouldComplete).toBe(false);
    });

    it("completion text includes trailing space for continued typing", () => {
      const result = shouldTabCompleteSuggestion(
        "/om",
        makeSelectedItem("omp"),
      );
      expect(result.completionText).toBe("/omp ");
    });
  });
});

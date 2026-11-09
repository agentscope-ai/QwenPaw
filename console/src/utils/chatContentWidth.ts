/**
 * Conversation column width preferences for the Chat page.
 *
 * The transcript and composer share one width axis (`--qwenpaw-chat-user-content-width`).
 * Drag handles on both edges of the column publish a symmetric width change and persist
 * the chosen px value, mirroring the conversation width controls shipped by the DSH web
 * frontend: a floor keeps the column readable, and a fixed edge budget keeps room for the
 * handles themselves so they never overlap the transcript.
 */

/** localStorage key holding the dragged transcript width preference in px. */
export const CHAT_CONTENT_WIDTH_STORAGE_KEY = "qwenpaw_chat_content_width";

/** Floor for a dragged conversation column width. */
export const CHAT_CONTENT_WIDTH_MIN = 640;

/** Width used before the user ever drags a conversation edge. */
export const CHAT_CONTENT_WIDTH_DEFAULT = 960;

/** Horizontal room reserved outside the column for both handles and safe edges. */
export const CHAT_CONTENT_WIDTH_EDGE_BUDGET = 176;

/** Gap kept between a handle strip's inner edge and the conversation column edge. */
export const CHAT_CONTENT_WIDTH_HANDLE_GAP = 16;

/** Width of one handle's pointer target; the visible line stays 2px thin. */
export const CHAT_CONTENT_WIDTH_HANDLE_WIDTH = 28;

/** Smallest spare margin that still leaves room for a visible handle strip. */
export const CHAT_CONTENT_WIDTH_MIN_SPARE =
  CHAT_CONTENT_WIDTH_HANDLE_GAP + CHAT_CONTENT_WIDTH_HANDLE_WIDTH + 4;

/** Keyboard step (px of column width) for an accessible width change. */
export const CHAT_CONTENT_WIDTH_KEYBOARD_STEP = 16;

/** Read the persisted width preference, or null when absent or corrupt. */
export function readChatContentWidthPreference(): number | null {
  try {
    const raw = localStorage.getItem(CHAT_CONTENT_WIDTH_STORAGE_KEY);
    if (raw === null) return null;
    const value = Number(raw);
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

/** Persist (or clear, with null) the width preference. */
export function writeChatContentWidthPreference(width: number | null): void {
  try {
    if (width === null) {
      localStorage.removeItem(CHAT_CONTENT_WIDTH_STORAGE_KEY);
      return;
    }
    localStorage.setItem(
      CHAT_CONTENT_WIDTH_STORAGE_KEY,
      String(Math.round(width)),
    );
  } catch {
    // storage unavailable
  }
}

/** Maximum column width a drag may produce for the measured column. */
export function maxChatContentWidth(columnWidth: number): number {
  return Math.max(
    CHAT_CONTENT_WIDTH_MIN,
    Math.round(columnWidth) - CHAT_CONTENT_WIDTH_EDGE_BUDGET,
  );
}

/** Clamp a requested width into the column's draggable range. */
export function clampChatContentWidth(
  width: number,
  columnWidth: number,
): number {
  return Math.min(
    maxChatContentWidth(columnWidth),
    Math.max(CHAT_CONTENT_WIDTH_MIN, Math.round(width)),
  );
}

/**
 * Resolve the width the transcript should render for one measured column.
 * Without a stored preference the column keeps its shipped width (full column up
 * to the default cap); a stored preference is clamped into the draggable range.
 */
export function resolveChatContentWidth(
  columnWidth: number,
  preference: number | null,
): number {
  if (preference !== null)
    return clampChatContentWidth(preference, columnWidth);
  return Math.max(
    0,
    Math.min(CHAT_CONTENT_WIDTH_DEFAULT, Math.round(columnWidth)),
  );
}

/** Whether the measured column leaves enough spare room for visible handles. */
export function canResizeChatContent(
  columnWidth: number,
  contentWidth: number,
): boolean {
  const spare = (Math.round(columnWidth) - Math.round(contentWidth)) / 2;
  return spare >= CHAT_CONTENT_WIDTH_MIN_SPARE;
}

/** Convert an outward handle offset (px) into a symmetric width delta. */
export function contentWidthFromHandleOffset(
  baseWidth: number,
  outwardOffset: number,
  columnWidth: number,
): number {
  return clampChatContentWidth(
    baseWidth + Math.round(outwardOffset) * 2,
    columnWidth,
  );
}

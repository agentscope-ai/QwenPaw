/**
 * Types and limits shared by the Office preview. Kept free of heavy
 * dependencies so FilePreview can import it without pulling the zip / docx
 * libraries from `officeDocument.ts` into the main bundle.
 */

export type OfficeKind = "docx" | "xlsx" | "pptx";

export interface SheetPreview {
  name: string;
  /** At most `MAX_SHEET_ROWS` x `MAX_SHEET_COLS` cells, as display text. */
  rows: string[][];
  totalRows: number;
  totalCols: number;
}

export interface SlidePreview {
  index: number;
  paragraphs: string[];
}

export const MAX_OFFICE_FILE_BYTES = 25 * 1024 * 1024;
export const MAX_SHEET_ROWS = 500;
export const MAX_SHEET_COLS = 50;

export function getOfficeKind(filePath: string): OfficeKind | null {
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  return ext === "docx" || ext === "xlsx" || ext === "pptx" ? ext : null;
}

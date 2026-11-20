/**
 * Client-side readers for Office Open XML files (docx / xlsx / pptx).
 *
 * The preview drawer cannot rely on a server-side converter, so the files are
 * unpacked in the browser. docx is converted to HTML with mammoth; xlsx and
 * pptx are small enough to read straight out of the zip container, which
 * avoids shipping a spreadsheet engine just for a read-only preview.
 *
 * This module is imported lazily so that the zip/docx libraries stay out of
 * the main bundle until an Office file is actually opened.
 */

import JSZip from "jszip";
import {
  MAX_SHEET_COLS,
  MAX_SHEET_ROWS,
  type SheetPreview,
  type SlidePreview,
} from "./officeTypes";

const REL_NS =
  "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

// ---------------------------------------------------------------------------
// XML helpers
// ---------------------------------------------------------------------------

function parseXml(text: string): Document {
  const doc = new DOMParser().parseFromString(text, "application/xml");
  if (doc.getElementsByTagName("parsererror").length > 0) {
    throw new Error("Malformed XML in Office document");
  }
  return doc;
}

async function readXml(zip: JSZip, path: string): Promise<Document | null> {
  const entry = zip.file(path);
  return entry ? parseXml(await entry.async("string")) : null;
}

function elements(root: Document | Element, localName: string): Element[] {
  return Array.from(root.getElementsByTagNameNS("*", localName));
}

/** Resolve a relationship target to a zip path, relative to `baseDir`. */
function resolveTarget(baseDir: string, target: string): string {
  if (target.startsWith("/")) return target.slice(1);
  const parts = `${baseDir}/${target}`.split("/");
  const resolved: string[] = [];
  for (const part of parts) {
    if (part === "..") resolved.pop();
    else if (part && part !== ".") resolved.push(part);
  }
  return resolved.join("/");
}

async function readRelationships(
  zip: JSZip,
  relsPath: string,
  baseDir: string,
): Promise<Map<string, string>> {
  const map = new Map<string, string>();
  const doc = await readXml(zip, relsPath);
  if (!doc) return map;
  for (const rel of elements(doc, "Relationship")) {
    const id = rel.getAttribute("Id");
    const target = rel.getAttribute("Target");
    if (id && target) map.set(id, resolveTarget(baseDir, target));
  }
  return map;
}

async function loadZip(data: ArrayBuffer): Promise<JSZip> {
  return JSZip.loadAsync(data);
}

// ---------------------------------------------------------------------------
// docx
// ---------------------------------------------------------------------------

export async function docxToHtml(data: ArrayBuffer): Promise<string> {
  const mammoth = await import("mammoth");
  const result = await mammoth.convertToHtml({ arrayBuffer: data });
  return result.value;
}

// ---------------------------------------------------------------------------
// xlsx
// ---------------------------------------------------------------------------

const BUILTIN_DATE_FORMAT_IDS = new Set([
  14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47,
]);

function isDateFormatCode(code: string): boolean {
  // Drop quoted literals, escaped characters, colours and conditions before
  // looking for date/time tokens such as the "d" in "General \d".
  const stripped = code
    .replace(/"[^"]*"/g, "")
    .replace(/\\./g, "")
    .replace(/\[[^\]]*\]/g, "");
  return /[dmyhs]/i.test(stripped);
}

async function readDateStyles(zip: JSZip): Promise<Set<number>> {
  const dateStyles = new Set<number>();
  const doc = await readXml(zip, "xl/styles.xml");
  if (!doc) return dateStyles;
  const customDateIds = new Set<number>();
  for (const fmt of elements(doc, "numFmt")) {
    const id = Number(fmt.getAttribute("numFmtId"));
    if (isDateFormatCode(fmt.getAttribute("formatCode") ?? "")) {
      customDateIds.add(id);
    }
  }
  const cellXfs = elements(doc, "cellXfs")[0];
  const xfs = cellXfs ? elements(cellXfs, "xf") : [];
  xfs.forEach((xf, index) => {
    const id = Number(xf.getAttribute("numFmtId"));
    if (BUILTIN_DATE_FORMAT_IDS.has(id) || customDateIds.has(id)) {
      dateStyles.add(index);
    }
  });
  return dateStyles;
}

function formatExcelDate(serial: number): string {
  if (!Number.isFinite(serial)) return String(serial);
  // Excel's 1900 epoch (with its leap-year bug) is 1899-12-30 for serials > 60.
  const date = new Date(Math.round((serial - 25569) * 86400 * 1000));
  if (Number.isNaN(date.getTime())) return String(serial);
  const iso = date.toISOString();
  return Number.isInteger(serial)
    ? iso.slice(0, 10)
    : iso.slice(0, 19).replace("T", " ");
}

async function readSharedStrings(zip: JSZip): Promise<string[]> {
  const doc = await readXml(zip, "xl/sharedStrings.xml");
  if (!doc) return [];
  return elements(doc, "si").map((si) =>
    elements(si, "t")
      // Skip phonetic guides (<rPh><t>) that would duplicate the text.
      .filter((t) => t.parentNode?.nodeName.split(":").pop() !== "rPh")
      .map((t) => t.textContent ?? "")
      .join(""),
  );
}

function columnIndex(ref: string): number {
  const letters = /^[A-Za-z]+/.exec(ref)?.[0].toUpperCase() ?? "";
  let index = 0;
  for (const ch of letters) index = index * 26 + (ch.charCodeAt(0) - 64);
  return index - 1;
}

function childText(cell: Element, localName: string): string | null {
  const child = Array.from(cell.children).find(
    (el) => el.localName === localName,
  );
  return child ? child.textContent ?? "" : null;
}

function readCell(
  cell: Element,
  sharedStrings: string[],
  dateStyles: Set<number>,
): string {
  const type = cell.getAttribute("t");
  if (type === "inlineStr") {
    const inline = Array.from(cell.children).find(
      (el) => el.localName === "is",
    );
    return inline
      ? elements(inline, "t")
          .map((t) => t.textContent ?? "")
          .join("")
      : "";
  }
  const raw = childText(cell, "v");
  if (raw === null) return "";
  if (type === "s") return sharedStrings[Number(raw)] ?? "";
  if (type === "b") return raw === "1" ? "TRUE" : "FALSE";
  if (type === "str" || type === "e") return raw;
  if (dateStyles.has(Number(cell.getAttribute("s")))) {
    return formatExcelDate(Number(raw));
  }
  return raw;
}

function readSheet(
  doc: Document,
  sharedStrings: string[],
  dateStyles: Set<number>,
): Omit<SheetPreview, "name"> {
  const rows: string[][] = [];
  let totalRows = 0;
  let totalCols = 0;
  let lastRowNumber = 0;
  for (const row of elements(doc, "row")) {
    const rowNumber = Number(row.getAttribute("r")) || lastRowNumber + 1;
    lastRowNumber = rowNumber;
    const cells: string[] = [];
    let nextCol = 0;
    for (const cell of Array.from(row.children)) {
      if (cell.localName !== "c") continue;
      const ref = cell.getAttribute("r");
      const col = ref ? columnIndex(ref) : nextCol;
      nextCol = col + 1;
      const text = readCell(cell, sharedStrings, dateStyles);
      if (text === "") continue;
      totalCols = Math.max(totalCols, col + 1);
      if (col < MAX_SHEET_COLS) cells[col] = text;
    }
    if (cells.length === 0) continue;
    totalRows = Math.max(totalRows, rowNumber);
    if (rowNumber <= MAX_SHEET_ROWS) {
      while (rows.length < rowNumber) rows.push([]);
      rows[rowNumber - 1] = Array.from(cells, (cell) => cell ?? "");
    }
  }
  return { rows, totalRows, totalCols };
}

export async function readXlsx(data: ArrayBuffer): Promise<SheetPreview[]> {
  const zip = await loadZip(data);
  const workbook = await readXml(zip, "xl/workbook.xml");
  if (!workbook) throw new Error("Not a valid xlsx workbook");
  const rels = await readRelationships(zip, "xl/_rels/workbook.xml.rels", "xl");
  const [sharedStrings, dateStyles] = await Promise.all([
    readSharedStrings(zip),
    readDateStyles(zip),
  ]);
  const sheets: SheetPreview[] = [];
  for (const sheet of elements(workbook, "sheet")) {
    const path = rels.get(sheet.getAttributeNS(REL_NS, "id") ?? "");
    const doc = path ? await readXml(zip, path) : null;
    if (!doc) continue;
    sheets.push({
      name: sheet.getAttribute("name") ?? `Sheet${sheets.length + 1}`,
      ...readSheet(doc, sharedStrings, dateStyles),
    });
  }
  return sheets;
}

// ---------------------------------------------------------------------------
// pptx
// ---------------------------------------------------------------------------

export async function readPptx(data: ArrayBuffer): Promise<SlidePreview[]> {
  const zip = await loadZip(data);
  const presentation = await readXml(zip, "ppt/presentation.xml");
  if (!presentation) throw new Error("Not a valid pptx presentation");
  const rels = await readRelationships(
    zip,
    "ppt/_rels/presentation.xml.rels",
    "ppt",
  );
  const slides: SlidePreview[] = [];
  for (const slideId of elements(presentation, "sldId")) {
    const path = rels.get(slideId.getAttributeNS(REL_NS, "id") ?? "");
    const doc = path ? await readXml(zip, path) : null;
    if (!doc) continue;
    const paragraphs = elements(doc, "p")
      .filter((p) => p.namespaceURI?.endsWith("/drawingml/2006/main"))
      .map((p) =>
        elements(p, "t")
          .map((t) => t.textContent ?? "")
          .join(""),
      )
      .filter((text) => text.trim() !== "");
    slides.push({ index: slides.length + 1, paragraphs });
  }
  return slides;
}

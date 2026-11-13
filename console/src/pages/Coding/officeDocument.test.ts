import JSZip from "jszip";
import { describe, expect, it } from "vitest";
import { docxToHtml, readPptx, readXlsx } from "./officeDocument";
import { MAX_SHEET_COLS, MAX_SHEET_ROWS, getOfficeKind } from "./officeTypes";

const MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
const REL_NS =
  "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const PKG_REL_NS =
  "http://schemas.openxmlformats.org/package/2006/relationships";

async function zipBuffer(files: Record<string, string>): Promise<ArrayBuffer> {
  const zip = new JSZip();
  for (const [name, content] of Object.entries(files)) zip.file(name, content);
  return zip.generateAsync({ type: "arraybuffer" });
}

function relationships(entries: Record<string, string>): string {
  const items = Object.entries(entries)
    .map(([id, target]) => `<Relationship Id="${id}" Target="${target}"/>`)
    .join("");
  return `<Relationships xmlns="${PKG_REL_NS}">${items}</Relationships>`;
}

function workbook(sheets: Array<[string, string]>): string {
  const items = sheets
    .map(([name, rid]) => `<sheet name="${name}" sheetId="1" r:id="${rid}"/>`)
    .join("");
  return `<workbook xmlns="${MAIN_NS}" xmlns:r="${REL_NS}"><sheets>${items}</sheets></workbook>`;
}

describe("getOfficeKind", () => {
  it("maps Open XML extensions case-insensitively", () => {
    expect(getOfficeKind("a/b.DOCX")).toBe("docx");
    expect(getOfficeKind("b.xlsx")).toBe("xlsx");
    expect(getOfficeKind("b.pptx")).toBe("pptx");
    expect(getOfficeKind("b.doc")).toBeNull();
    expect(getOfficeKind("docx")).toBe("docx");
  });
});

describe("readXlsx", () => {
  it("reads shared strings, numbers, booleans, inline strings and dates", async () => {
    const data = await zipBuffer({
      "xl/workbook.xml": workbook([
        ["Sales", "rId1"],
        ["Empty", "rId2"],
      ]),
      "xl/_rels/workbook.xml.rels": relationships({
        rId1: "worksheets/sheet1.xml",
        rId2: "/xl/worksheets/sheet2.xml",
      }),
      "xl/sharedStrings.xml": `<sst xmlns="${MAIN_NS}">
        <si><t>Region</t></si>
        <si><r><t>Rich </t></r><r><t>text</t></r><rPh><t>PHONETIC</t></rPh></si>
      </sst>`,
      "xl/styles.xml": `<styleSheet xmlns="${MAIN_NS}">
        <numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd hh:mm"/></numFmts>
        <cellXfs count="3">
          <xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/>
        </cellXfs>
      </styleSheet>`,
      "xl/worksheets/sheet1.xml": `<worksheet xmlns="${MAIN_NS}"><sheetData>
        <row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>
        <row r="3">
          <c r="A3"><v>12.5</v></c>
          <c r="B3" t="b"><v>1</v></c>
          <c r="C3" t="inlineStr"><is><t>inline</t></is></c>
          <c r="D3" s="1"><v>45000</v></c>
          <c r="E3" s="2"><v>45000.5</v></c>
          <c r="F3" t="str"><f>A3*2</f><v>25</v></c>
        </row>
      </sheetData></worksheet>`,
      "xl/worksheets/sheet2.xml": `<worksheet xmlns="${MAIN_NS}"><sheetData/></worksheet>`,
    });

    const sheets = await readXlsx(data);

    expect(sheets.map((sheet) => sheet.name)).toEqual(["Sales", "Empty"]);
    expect(sheets[0].rows).toEqual([
      ["Region", "", "Rich text"],
      [],
      ["12.5", "TRUE", "inline", "2023-03-15", "2023-03-15 12:00:00", "25"],
    ]);
    expect(sheets[0].totalRows).toBe(3);
    expect(sheets[0].totalCols).toBe(6);
    expect(sheets[1].rows).toEqual([]);
  });

  it("caps rows and columns but still reports the real size", async () => {
    const cols = MAX_SHEET_COLS + 10;
    const rowsXml = Array.from({ length: MAX_SHEET_ROWS + 5 }, (_, r) => {
      const cells = Array.from({ length: cols }, (_, c) => {
        let name = "";
        for (let n = c + 1; n > 0; n = Math.floor((n - 1) / 26)) {
          name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
        }
        return `<c r="${name}${r + 1}"><v>${r}</v></c>`;
      }).join("");
      return `<row r="${r + 1}">${cells}</row>`;
    }).join("");
    const data = await zipBuffer({
      "xl/workbook.xml": workbook([["Big", "rId1"]]),
      "xl/_rels/workbook.xml.rels": relationships({
        rId1: "worksheets/sheet1.xml",
      }),
      "xl/worksheets/sheet1.xml": `<worksheet xmlns="${MAIN_NS}"><sheetData>${rowsXml}</sheetData></worksheet>`,
    });

    const [sheet] = await readXlsx(data);

    expect(sheet.rows).toHaveLength(MAX_SHEET_ROWS);
    expect(sheet.rows[0]).toHaveLength(MAX_SHEET_COLS);
    expect(sheet.totalRows).toBe(MAX_SHEET_ROWS + 5);
    expect(sheet.totalCols).toBe(cols);
  });

  it("rejects archives that are not workbooks", async () => {
    await expect(readXlsx(await zipBuffer({ "a.txt": "x" }))).rejects.toThrow();
  });

  it("rejects malformed XML", async () => {
    const data = await zipBuffer({ "xl/workbook.xml": "<workbook><sheets>" });
    await expect(readXlsx(data)).rejects.toThrow(/Malformed/);
  });
});

describe("readPptx", () => {
  const A = "http://schemas.openxmlformats.org/drawingml/2006/main";
  const P = "http://schemas.openxmlformats.org/presentationml/2006/main";
  const slide = (...paragraphs: string[][]) =>
    `<p:sld xmlns:p="${P}" xmlns:a="${A}"><p:cSld><p:spTree><p:sp><p:txBody>${paragraphs
      .map(
        (runs) =>
          `<a:p>${runs
            .map((run) => `<a:r><a:t>${run}</a:t></a:r>`)
            .join("")}</a:p>`,
      )
      .join("")}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>`;

  it("follows slide order from presentation.xml, not file names", async () => {
    const data = await zipBuffer({
      "ppt/presentation.xml": `<p:presentation xmlns:p="${P}" xmlns:r="${REL_NS}"><p:sldIdLst>
        <p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId1"/>
      </p:sldIdLst></p:presentation>`,
      "ppt/_rels/presentation.xml.rels": relationships({
        rId1: "slides/slide1.xml",
        rId2: "slides/slide2.xml",
      }),
      "ppt/slides/slide1.xml": slide(["Second ", "slide"]),
      "ppt/slides/slide2.xml": slide(["First"], [""], ["Details"]),
    });

    expect(await readPptx(data)).toEqual([
      { index: 1, paragraphs: ["First", "Details"] },
      { index: 2, paragraphs: ["Second slide"] },
    ]);
  });

  it("rejects archives that are not presentations", async () => {
    await expect(readPptx(await zipBuffer({ "a.txt": "x" }))).rejects.toThrow();
  });
});

describe("docxToHtml", () => {
  it("converts a minimal document to html", async () => {
    const W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
    const data = await zipBuffer({
      "[Content_Types].xml": `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
        <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
        <Default Extension="xml" ContentType="application/xml"/>
        <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
      </Types>`,
      "_rels/.rels": `<Relationships xmlns="${PKG_REL_NS}"><Relationship Id="rId1" Type="${REL_NS}/officeDocument" Target="word/document.xml"/></Relationships>`,
      "word/document.xml": `<w:document xmlns:w="${W}"><w:body>
        <w:p><w:r><w:t>Hello docx</w:t></w:r></w:p>
      </w:body></w:document>`,
    });

    expect(await docxToHtml(data)).toBe("<p>Hello docx</p>");
  });
});

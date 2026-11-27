import { Children, createContext, useContext, useMemo } from "react";
import type { ComponentProps } from "@ant-design/x-markdown";
import { MeasuredMessageWindow } from "./MeasuredMessageWindow";

const LargeTable = createContext({ large: false, columns: 1 });
const TABLE_ROW_THRESHOLD = 200;

export function WindowedMarkdownTable({
  children,
  domNode,
  className,
}: ComponentProps) {
  const body =
    domNode && "children" in domNode
      ? domNode.children.find((node) => "name" in node && node.name === "tbody")
      : undefined;
  const count =
    body && "children" in body
      ? body.children.filter((node) => "name" in node && node.name === "tr")
          .length
      : 0;
  const firstRow =
    body && "children" in body
      ? body.children.find((node) => "name" in node && node.name === "tr")
      : undefined;
  const columns =
    firstRow && "children" in firstRow
      ? firstRow.children.filter(
          (node) =>
            "name" in node && (node.name === "td" || node.name === "th"),
        ).length
      : 1;
  // Row spans cannot be removed independently without changing table geometry.
  const hasSpans =
    body &&
    "children" in body &&
    body.children.some(
      (row) =>
        "children" in row &&
        row.children.some(
          (cell) =>
            "attribs" in cell && (cell.attribs.rowspan || cell.attribs.colspan),
        ),
    );
  const large = count > TABLE_ROW_THRESHOLD && !hasSpans;
  return (
    <LargeTable.Provider value={{ large, columns }}>
      <table
        className={className}
        style={
          large
            ? {
                display: "table",
                tableLayout: "fixed",
                width: "100%",
                overflowWrap: "anywhere",
              }
            : undefined
        }
      >
        {children}
      </table>
    </LargeTable.Provider>
  );
}

export function WindowedMarkdownTableBody({ children }: ComponentProps) {
  const { large, columns } = useContext(LargeTable);
  const rows = Children.toArray(children).filter(
    (child) => typeof child !== "string",
  );
  const count = rows.length;
  const ids = useMemo(
    () => Array.from({ length: count }, (_, i) => `table-row:${i}`),
    [count],
  );
  if (!large) return <tbody>{children}</tbody>;
  return (
    <MeasuredMessageWindow
      ids={ids}
      tableColumns={columns}
      estimate={56}
      maxItems={128}
    >
      {(index) => rows[index]}
    </MeasuredMessageWindow>
  );
}

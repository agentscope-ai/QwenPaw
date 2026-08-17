import type { ReactNode } from "react";

/**
 * Dependency-free markdown rendering for assistant replies.
 *
 * The embedded cloud console renders analyst output through a full chat
 * component library; this shell stays dependency-free, so a focused subset
 * is implemented here: headings, paragraphs, lists, GFM tables, fenced
 * code, blockquotes, rules, and bold/italic/code/link inlines. Output is
 * built as React nodes (never raw HTML), so untrusted model output cannot
 * inject markup.
 */

const INLINE_PATTERN = new RegExp(
  [
    "(`[^`\\n]+`)",
    "(\\*\\*[^*\\n]+\\*\\*)",
    "(\\*[^*\\n]+\\*)",
    "(\\[[^\\]\\n]+\\]\\(https?://[^\\s)]+\\))",
  ].join("|"),
  "g",
);

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let index = 0;
  for (const match of text.matchAll(INLINE_PATTERN)) {
    const start = match.index ?? 0;
    if (start > cursor) nodes.push(text.slice(cursor, start));
    const token = match[0];
    const key = `${keyPrefix}-${index++}`;
    if (token.startsWith("`")) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<b key={key}>{renderInline(token.slice(2, -2), key)}</b>);
    } else if (token.startsWith("*")) {
      nodes.push(<em key={key}>{renderInline(token.slice(1, -1), key)}</em>);
    } else {
      const link = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
      if (link) {
        nodes.push(
          <a href={link[2]} key={key} rel="noreferrer noopener" target="_blank">
            {link[1]}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    }
    cursor = start + token.length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function isTableRow(line: string): boolean {
  return line.trim().startsWith("|") || line.includes(" | ");
}

function isTableSeparator(line: string): boolean {
  const trimmed = line.trim();
  return /^\|?[\s:|-]+\|?$/.test(trimmed) && trimmed.includes("-");
}

function splitTableRow(line: string): string[] {
  let trimmed = line.trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
  return trimmed.split("|").map((cell) => cell.trim());
}

interface ListItem {
  ordered: boolean;
  text: string;
}

export function renderMarkdown(text: string): ReactNode[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let key = 0;
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i += 1;
      continue;
    }

    // Fenced code block.
    if (trimmed.startsWith("```")) {
      const buffer: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buffer.push(lines[i]);
        i += 1;
      }
      i += 1; // closing fence
      blocks.push(
        <pre key={key++}>
          <code>{buffer.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    // Heading (5-6 hashes render at the smallest supported level).
    const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const level = Math.min(heading[1].length, 4);
      const content = renderInline(heading[2], `h${key}`);
      blocks.push(
        level === 1 ? (
          <h1 key={key++}>{content}</h1>
        ) : level === 2 ? (
          <h2 key={key++}>{content}</h2>
        ) : level === 3 ? (
          <h3 key={key++}>{content}</h3>
        ) : (
          <h4 key={key++}>{content}</h4>
        ),
      );
      i += 1;
      continue;
    }

    // Horizontal rule.
    if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
      blocks.push(<hr key={key++} />);
      i += 1;
      continue;
    }

    // GFM table: header row followed by a separator row.
    if (
      isTableRow(trimmed) &&
      i + 1 < lines.length &&
      isTableSeparator(lines[i + 1])
    ) {
      const header = splitTableRow(trimmed);
      i += 2;
      const rows: string[][] = [];
      while (
        i < lines.length &&
        isTableRow(lines[i].trim()) &&
        lines[i].trim()
      ) {
        rows.push(splitTableRow(lines[i]));
        i += 1;
      }
      blocks.push(
        <table key={key++}>
          <thead>
            <tr>
              {header.map((cell, cellIndex) => (
                <th key={cellIndex}>{renderInline(cell, `th${cellIndex}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>
                    {renderInline(cell, `td${rowIndex}-${cellIndex}`)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
      continue;
    }

    // Blockquote.
    if (trimmed.startsWith("> ")) {
      const buffer: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("> ")) {
        buffer.push(lines[i].trim().slice(2));
        i += 1;
      }
      blocks.push(
        <blockquote key={key++}>
          {renderMarkdown(buffer.join("\n"))}
        </blockquote>,
      );
      continue;
    }

    // List (flat; ordered and unordered runs kept separate).
    const listMatch = trimmed.match(/^([-*]|\d+[.)])\s+(.*)$/);
    if (listMatch) {
      const items: ListItem[] = [];
      while (i < lines.length) {
        const itemMatch = lines[i].trim().match(/^([-*]|\d+[.)])\s+(.*)$/);
        if (!itemMatch) break;
        items.push({
          ordered: /\d/.test(itemMatch[1]),
          text: itemMatch[2],
        });
        i += 1;
      }
      const ordered = items[0]?.ordered ?? false;
      const children = items.map((item, itemIndex) => (
        <li key={itemIndex}>{renderInline(item.text, `li${itemIndex}`)}</li>
      ));
      blocks.push(
        ordered ? (
          <ol key={key++}>{children}</ol>
        ) : (
          <ul key={key++}>{children}</ul>
        ),
      );
      continue;
    }

    // Paragraph: consecutive plain lines with soft breaks preserved.
    const buffer: string[] = [];
    while (i < lines.length) {
      const current = lines[i].trim();
      if (
        !current ||
        current.startsWith("```") ||
        current.startsWith("#") ||
        current.startsWith("> ") ||
        /^([-*]|\d+[.)])\s+/.test(current) ||
        (isTableRow(current) &&
          i + 1 < lines.length &&
          isTableSeparator(lines[i + 1]))
      ) {
        break;
      }
      buffer.push(current);
      i += 1;
    }
    // Guarantee progress: a line that resembles block syntax but failed its
    // branch pattern (e.g. "#not-a-heading") reaches here with an empty
    // buffer; consume it as plain text so the outer loop always advances.
    if (buffer.length === 0) {
      buffer.push(trimmed);
      i += 1;
    }
    blocks.push(
      <p key={key++}>
        {buffer.flatMap((part, partIndex) =>
          partIndex === 0
            ? renderInline(part, `p${key}-${partIndex}`)
            : [
                <br key={`br${partIndex}`} />,
                ...renderInline(part, `p${key}-${partIndex}`),
              ],
        )}
      </p>,
    );
  }

  return blocks;
}

/**
 * Split the agent's trailing completion marker (〚 … 〛) off the reply body
 * so it can be rendered as a run summary instead of raw prose.
 */
export function splitCompletionMarker(text: string): {
  body: string;
  marker: string;
} {
  const match = text.match(/〚([\s\S]*?)〛\s*$/);
  if (!match || match.index === undefined) {
    return { body: text, marker: "" };
  }
  return {
    body: text.slice(0, match.index).trimEnd(),
    marker: match[1].trim(),
  };
}

import type React from "react";

export interface TocItem {
  level: 2 | 3;
  text: string;
  id: string;
}

export interface FaqItem {
  question: string;
  answer: string;
}

/** Build URL-safe id from heading text (en + zh). */
export function slugifyHeading(text: string): string {
  const s = text
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-zA-Z0-9_\-\u4e00-\u9fa5]/g, "");
  return s || "section";
}

/** Extract h2/h3 from markdown in order. */
export function parseToc(md: string): TocItem[] {
  const toc: TocItem[] = [];
  const idCounter = new Map<string, number>();
  const re = /^#{2,3}\s+(.+)$/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(md)) !== null) {
    const level = m[0].startsWith("###") ? 3 : 2;
    const text = m[1].replace(/#+\s*$/, "").trim();
    const baseId = slugifyHeading(text);
    const count = (idCounter.get(baseId) ?? 0) + 1;
    idCounter.set(baseId, count);
    const id = count === 1 ? baseId : `${baseId}-${count}`;
    toc.push({ level, text, id });
  }
  return toc;
}

/** Flatten React children to string for slug. */
export function headingText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(headingText).join("");
  if (children && typeof children === "object" && "props" in children)
    return headingText(
      (children as React.ReactElement).props.children as React.ReactNode,
    );
  return "";
}

export function parseFaqContent(md: string): {
  intro: string;
  items: FaqItem[];
} {
  const lines = md.split("\n");
  const introLines: string[] = [];
  const items: FaqItem[] = [];
  let currentQuestion: string | null = null;
  let currentAnswerLines: string[] = [];

  const flush = () => {
    if (!currentQuestion) return;
    items.push({
      question: currentQuestion,
      answer: currentAnswerLines.join("\n").trim(),
    });
    currentQuestion = null;
    currentAnswerLines = [];
  };

  for (const line of lines) {
    const m = line.match(/^###\s+(.+)$/);
    if (m) {
      flush();
      currentQuestion = m[1].trim();
      continue;
    }
    if (currentQuestion === null) introLines.push(line);
    else currentAnswerLines.push(line);
  }
  flush();

  return {
    intro: introLines.join("\n").trim(),
    items,
  };
}

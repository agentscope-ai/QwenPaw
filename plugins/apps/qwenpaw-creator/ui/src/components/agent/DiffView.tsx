/**
 * Minimal line-level diff for review operations.
 *
 * Text values render as red (removed) / green (added) lines so a reviewer can
 * see exactly what an AgentDock change did.  Non-string values are pretty
 * printed as JSON first, then diffed line by line.  The algorithm is a compact
 * longest-common-subsequence walk — small review payloads never need more.
 */

type DiffLineKind = "context" | "added" | "removed";

interface DiffLine {
  kind: DiffLineKind;
  text: string;
}

function toLines(value: unknown): string[] {
  if (value === undefined || value === null) return [];
  const text = typeof value === "string" ? value : safeStringify(value);
  return text.split("\n");
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function diffLines(before: string[], after: string[]): DiffLine[] {
  const rows = before.length;
  const cols = after.length;
  const lcs: number[][] = Array.from({ length: rows + 1 }, () =>
    new Array<number>(cols + 1).fill(0),
  );
  for (let i = rows - 1; i >= 0; i -= 1) {
    for (let j = cols - 1; j >= 0; j -= 1) {
      lcs[i][j] =
        before[i] === after[j]
          ? lcs[i + 1][j + 1] + 1
          : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < rows && j < cols) {
    if (before[i] === after[j]) {
      result.push({ kind: "context", text: before[i] });
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      result.push({ kind: "removed", text: before[i] });
      i += 1;
    } else {
      result.push({ kind: "added", text: after[j] });
      j += 1;
    }
  }
  while (i < rows) {
    result.push({ kind: "removed", text: before[i] });
    i += 1;
  }
  while (j < cols) {
    result.push({ kind: "added", text: after[j] });
    j += 1;
  }
  return result;
}

const LINE_STYLE: Record<DiffLineKind, string> = {
  context: "text-[var(--color-text-secondary)]",
  added:
    "bg-[var(--color-success-soft,#0f5132)]/25 text-[var(--color-success,#3fb950)]",
  removed:
    "bg-[var(--color-danger-soft,#5c1a1a)]/25 text-[var(--color-danger,#f85149)] line-through/0",
};

const LINE_PREFIX: Record<DiffLineKind, string> = {
  context: "\u00a0",
  added: "+",
  removed: "-",
};

export default function DiffView({
  before,
  after,
}: {
  before: unknown;
  after: unknown;
}) {
  const lines = diffLines(toLines(before), toLines(after));
  if (lines.length === 0) {
    return (
      <p className="rounded-md bg-[var(--color-bg-secondary)] p-2 text-[10px] text-[var(--color-text-tertiary)]">
        （无内容变化）
      </p>
    );
  }
  return (
    <div
      data-review-diff
      className="max-h-60 overflow-auto rounded-md bg-[var(--color-bg-secondary)] p-1 font-mono text-[10px] leading-4"
    >
      {lines.map((line, index) => (
        <div
          key={`${line.kind}-${index}`}
          data-diff-kind={line.kind}
          className={`flex gap-1 whitespace-pre-wrap break-all px-1 ${
            LINE_STYLE[line.kind]
          }`}
        >
          <span aria-hidden className="select-none opacity-60">
            {LINE_PREFIX[line.kind]}
          </span>
          <span className="min-w-0 flex-1">{line.text || "\u00a0"}</span>
        </div>
      ))}
    </div>
  );
}

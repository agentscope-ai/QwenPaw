/**
 * Module-scoped record of the most recent copy-from-editor action.
 *
 * Cmd/Ctrl+C in the Coding-mode editor writes plain text to the system
 * clipboard (default Monaco behavior) and ALSO stashes the copied text
 * + source coordinates here. The Chat composer's paste handler reads
 * this back: if the pasted text matches `text` exactly, the textarea
 * receives the formatted `path:line[-line]` (plus optional fenced code)
 * version instead of the raw text — so pastes outside Chat stay plain
 * but Chat-bound pastes carry editor context.
 */
export interface LastEditorCopy {
  text: string;
  formatted: string;
  // Wall-clock ms; consumers may ignore stale entries.
  ts: number;
}

let last: LastEditorCopy | null = null;

export function setLastEditorCopy(entry: LastEditorCopy): void {
  last = entry;
}

export function getLastEditorCopy(): LastEditorCopy | null {
  return last;
}

export function clearLastEditorCopy(): void {
  last = null;
}

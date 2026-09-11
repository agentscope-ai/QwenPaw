import { useCallback, useEffect, useMemo, useState } from "react";
import type { ProjectEditOperation } from "@/store/projectSnapshotStore";
import { projectJsonPointer } from "@/lib/projectJsonPointer";
import i18n from "@/i18n";

type DraftRecord = Record<string, unknown>;

interface DraftChange {
  op: "add" | "replace" | "remove";
  tokens: string[];
  before?: unknown;
  value?: unknown;
}

interface DraftSession<T> {
  scopeKey: string;
  baseline: T;
  draft: T;
  conflictPaths: string[];
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function jsonEqual(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right)) return false;
    return (
      left.length === right.length &&
      left.every((value, index) => jsonEqual(value, right[index]))
    );
  }
  if (
    left !== null &&
    right !== null &&
    typeof left === "object" &&
    typeof right === "object"
  ) {
    const leftRecord = left as DraftRecord;
    const rightRecord = right as DraftRecord;
    const leftKeys = Object.keys(leftRecord).sort();
    const rightKeys = Object.keys(rightRecord).sort();
    return (
      leftKeys.length === rightKeys.length &&
      leftKeys.every(
        (key, index) =>
          key === rightKeys[index] &&
          jsonEqual(leftRecord[key], rightRecord[key]),
      )
    );
  }
  return false;
}

function collectChanges(
  before: unknown,
  after: unknown,
  tokens: string[] = [],
): DraftChange[] {
  if (jsonEqual(before, after)) return [];
  if (
    before !== null &&
    after !== null &&
    !Array.isArray(before) &&
    !Array.isArray(after) &&
    typeof before === "object" &&
    typeof after === "object"
  ) {
    const beforeRecord = before as DraftRecord;
    const afterRecord = after as DraftRecord;
    const beforeKeys = new Set(Object.keys(beforeRecord));
    const afterKeys = new Set(Object.keys(afterRecord));
    const changes: DraftChange[] = [];
    [...beforeKeys]
      .filter((key) => !afterKeys.has(key))
      .sort()
      .forEach((key) =>
        changes.push({
          op: "remove",
          tokens: [...tokens, key],
          before: clone(beforeRecord[key]),
        }),
      );
    [...afterKeys]
      .filter((key) => !beforeKeys.has(key))
      .sort()
      .forEach((key) =>
        changes.push({
          op: "add",
          tokens: [...tokens, key],
          value: clone(afterRecord[key]),
        }),
      );
    [...beforeKeys]
      .filter((key) => afterKeys.has(key))
      .sort()
      .forEach((key) =>
        changes.push(
          ...collectChanges(beforeRecord[key], afterRecord[key], [
            ...tokens,
            key,
          ]),
        ),
      );
    return changes;
  }
  return [
    {
      op: "replace",
      tokens,
      before: clone(before),
      value: clone(after),
    },
  ];
}

function overlaps(left: string[], right: string[]): boolean {
  const length = Math.min(left.length, right.length);
  return left.slice(0, length).every((token, index) => token === right[index]);
}

function relativePointer(tokens: string[]): string {
  return projectJsonPointer(...tokens);
}

function applyChange(target: unknown, change: DraftChange): void {
  if (change.tokens.length === 0) {
    throw new Error(i18n.t("lib.draftRootReplace"));
  }
  let parent = target as DraftRecord;
  for (const token of change.tokens.slice(0, -1)) {
    const child = parent[token];
    if (child === null || typeof child !== "object" || Array.isArray(child)) {
      throw new Error(
        i18n.t("lib.draftPathNotExist", {
          path: relativePointer(change.tokens),
        }),
      );
    }
    parent = child as DraftRecord;
  }
  const token = change.tokens.at(-1)!;
  if (change.op === "remove") delete parent[token];
  else parent[token] = clone(change.value);
}

function mergeAuthority<T>(
  session: DraftSession<T>,
  authority: T,
): DraftSession<T> {
  if (jsonEqual(session.baseline, authority)) return session;
  const localChanges = collectChanges(session.baseline, session.draft);
  const remoteChanges = collectChanges(session.baseline, authority);
  if (!localChanges.length) {
    return {
      ...session,
      baseline: clone(authority),
      draft: clone(authority),
      conflictPaths: [],
    };
  }
  const conflicts = localChanges
    .filter((local) =>
      remoteChanges.some((remote) => overlaps(local.tokens, remote.tokens)),
    )
    .map((change) => relativePointer(change.tokens));
  const nextDraft = clone(authority);
  try {
    localChanges.forEach((change) => applyChange(nextDraft, change));
  } catch {
    return {
      ...session,
      baseline: clone(authority),
      conflictPaths: [
        ...new Set([
          ...session.conflictPaths,
          ...conflicts,
          i18n.t("lib.structureModified"),
        ]),
      ],
    };
  }
  return {
    ...session,
    baseline: clone(authority),
    draft: nextDraft,
    conflictPaths: [...new Set([...session.conflictPaths, ...conflicts])],
  };
}

export interface ProjectDraftController<T> {
  value: T;
  dirty: boolean;
  dirtyCount: number;
  dirtyPaths: string[];
  conflictPaths: string[];
  operations: ProjectEditOperation[];
  update: (mutator: (draft: T) => void) => void;
  discard: () => void;
  acceptConflicts: () => void;
  markApplied: () => void;
}

/**
 * Maintain a page-local editable projection without mutating the authoritative
 * Project snapshot. Clean fields follow polling updates; dirty fields survive
 * disjoint updates and are explicitly flagged when another writer touches the
 * same JSON Pointer.
 */
export function useProjectDraft<T>(
  authority: T,
  scopeKey: string,
  rootSegments: Array<string | number>,
): ProjectDraftController<T> {
  const [session, setSession] = useState<DraftSession<T>>(() => ({
    scopeKey,
    baseline: clone(authority),
    draft: clone(authority),
    conflictPaths: [],
  }));

  useEffect(() => {
    setSession((current) =>
      current.scopeKey === scopeKey
        ? mergeAuthority(current, authority)
        : {
            scopeKey,
            baseline: clone(authority),
            draft: clone(authority),
            conflictPaths: [],
          },
    );
  }, [authority, scopeKey]);

  const active =
    session.scopeKey === scopeKey
      ? session
      : {
          scopeKey,
          baseline: authority,
          draft: authority,
          conflictPaths: [],
        };
  const changes = useMemo(
    () => collectChanges(active.baseline, active.draft),
    [active.baseline, active.draft],
  );
  const rootKey = rootSegments.map(String).join("\u0000");
  const operations = useMemo<ProjectEditOperation[]>(
    () =>
      changes.map((change) => ({
        op: change.op,
        path: projectJsonPointer(...rootSegments, ...change.tokens),
        ...(change.op === "remove"
          ? { before: change.before }
          : change.op === "add"
          ? { value: change.value, missingBefore: true }
          : { before: change.before, value: change.value }),
      })),
    [changes, rootKey],
  );

  const update = useCallback(
    (mutator: (draft: T) => void) => {
      setSession((current) => {
        const scoped =
          current.scopeKey === scopeKey
            ? current
            : {
                scopeKey,
                baseline: clone(authority),
                draft: clone(authority),
                conflictPaths: [],
              };
        const draft = clone(scoped.draft);
        mutator(draft);
        return { ...scoped, draft };
      });
    },
    [authority, scopeKey],
  );
  const discard = useCallback(() => {
    setSession((current) => ({
      ...current,
      baseline: clone(current.baseline),
      draft: clone(current.baseline),
      conflictPaths: [],
    }));
  }, []);
  const acceptConflicts = useCallback(() => {
    setSession((current) => ({ ...current, conflictPaths: [] }));
  }, []);
  const markApplied = useCallback(() => {
    setSession((current) => ({
      ...current,
      baseline: clone(current.draft),
      draft: clone(current.draft),
      conflictPaths: [],
    }));
  }, []);

  return {
    value: active.draft,
    dirty: changes.length > 0,
    dirtyCount: changes.length,
    dirtyPaths: changes.map((change) => relativePointer(change.tokens)),
    conflictPaths: active.conflictPaths,
    operations,
    update,
    discard,
    acceptConflicts,
    markApplied,
  };
}

import { useEffect, useRef, useState } from "react";
import { Alert, Button, Modal } from "antd";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import PromptTokenEditor, {
  type PromptTokenEditorHandle,
} from "@/components/workbench/PromptTokenEditor";
import type { PromptRichToken } from "@/components/workbench/PromptRichBlock";
import {
  promptReferenceSignature,
  promptTokenAt,
} from "./promptReferenceTokens";
import RelatedAssetPicker, {
  type PickerKind,
} from "@/components/workbench/RelatedAssetPicker";

/** A project asset that may be added as a brand-new [Image N] reference. */
export interface PromptRefCandidate {
  id: string;
  name: string;
  thumbUrl: string | null;
  /** Picker category; loose material versions omit it. */
  kind?: PickerKind;
}

/**
 * Shared fullscreen prompt editor (R2V workbench and the asset library use
 * the same editing mode): a token-pill canvas plus a right-hand reference
 * rail whose entries insert the pill itself at the caret. `candidates` lists
 * project assets not yet bound as references — they are browsed through the
 * same condensed asset-library picker as the R2V related-assets flow, so the
 * modal keeps a constant height however many assets the project has. Picking
 * assigns the next [Image N] indexes, inserts the pills, and reports the
 * bindings on 完成 so the host can persist them alongside the prompt.
 */
export default function PromptEditorModal({
  open,
  label,
  initialValue,
  sourceValue = initialValue,
  sourceKey = "",
  tokens,
  candidates = [],
  disabled = false,
  onCancel,
  onDone,
}: {
  open: boolean;
  label: string;
  initialValue: string;
  /** Raw persisted/draft text when initialValue is a public presentation. */
  sourceValue?: string;
  /** Owning field; an open draft must not silently move to another target. */
  sourceKey?: string;
  tokens: PromptRichToken[];
  candidates?: PromptRefCandidate[];
  disabled?: boolean;
  onCancel: () => void;
  onDone: (value: string, addedReferenceIds: string[]) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(initialValue);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [added, setAdded] = useState<
    Array<PromptRichToken & { candidateId: string }>
  >([]);
  const editorRef = useRef<PromptTokenEditorHandle>(null);
  const [baseline, setBaseline] = useState(() => ({
    sourceValue,
    sourceKey,
    presentedValue: initialValue,
    references: promptReferenceSignature(tokens),
    tokens,
  }));
  const [editorSeed, setEditorSeed] = useState(initialValue);
  const [editorRevision, setEditorRevision] = useState(0);
  const reload = () => {
    setBaseline({
      sourceValue,
      sourceKey,
      presentedValue: initialValue,
      references: promptReferenceSignature(tokens),
      tokens,
    });
    setDraft(initialValue);
    setEditorSeed(initialValue);
    setEditorRevision((revision) => revision + 1);
    setAdded([]);
    setPickerOpen(false);
  };
  useEffect(() => {
    if (!open) return;
    reload();
    // Sample once per opening. Background updates are compared below, never
    // assigned over an in-progress edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const referencesChanged =
    baseline.references !== promptReferenceSignature(tokens);
  const scopeChanged = baseline.sourceKey !== sourceKey;
  const textChanged = baseline.sourceValue !== sourceValue;
  const conflict = open && (referencesChanged || scopeChanged || textChanged);
  const finish = () => {
    if (disabled || conflict) return;
    // Public names can refresh while raw text and reference identity stay
    // unchanged. An untouched editor still accepts the current presentation
    // so its host can preserve the exact raw source text.
    onDone(
      draft === baseline.presentedValue && added.length === 0
        ? initialValue
        : draft,
      added.map((token) => token.candidateId),
    );
  };
  // Keep the editor's original image bindings visible while conflicts are
  // resolved. Reinterpreting its existing [Image N] against a new list would
  // silently point the user's draft at a different asset.
  const allTokens = [...baseline.tokens, ...added];
  const addedIds = new Set(added.map((token) => token.candidateId));
  const openCandidates = candidates.filter(
    (candidate) => !addedIds.has(candidate.id),
  );
  const addCandidates = (ids: string[]) => {
    const picked = ids
      .map((id) => openCandidates.find((candidate) => candidate.id === id))
      .filter((candidate): candidate is PromptRefCandidate =>
        Boolean(candidate),
      );
    if (picked.length === 0) return;
    let index = allTokens.reduce(
      (max, token) =>
        Number.isSafeInteger(token.index) && token.index > 0
          ? Math.max(max, token.index)
          : max,
      0,
    );
    const newTokens = picked.map((candidate) => {
      index += 1;
      return {
        candidateId: candidate.id,
        index,
        name: candidate.name,
        kind: "artifact" as const,
        thumbUrl: candidate.thumbUrl,
        referenceId: candidate.id,
      };
    });
    setAdded((previous) => [...previous, ...newTokens]);
    // The editor reads tokens through a ref updated on render; defer the
    // inserts one frame so the new tokens are resolvable. insertToken moves
    // the caret behind each pill, so sequential calls chain naturally.
    requestAnimationFrame(() => {
      for (const token of newTokens)
        editorRef.current?.insertToken(token.index);
    });
  };

  return (
    <Modal
      open={open}
      onCancel={onCancel}
      width="min(960px, 94vw)"
      title={
        <span className="text-sm font-bold">
          {t("r2v.fullscreenEditTitle", { label })}
          <span className="ml-2 text-[11px] font-normal text-[var(--color-text-tertiary)]">
            {t("r2v.promptChars", {
              count: draft.replace(/\s/g, "").length,
            })}
          </span>
        </span>
      }
      footer={
        <div className="flex justify-end gap-2">
          <Button size="small" onClick={onCancel}>
            {t("r2v.fullscreenCancel")}
          </Button>
          <Button
            size="small"
            type="primary"
            disabled={disabled || conflict}
            data-prompt-editor-done
            onClick={finish}
          >
            {t("r2v.fullscreenDone")}
          </Button>
        </div>
      }
      destroyOnHidden
    >
      {conflict && (
        <Alert
          className="mb-3"
          type="warning"
          showIcon
          message={t("r2v.editorChangedTitle", {
            defaultValue: "提示词已在其他位置更新",
          })}
          description={
            referencesChanged || scopeChanged
              ? t("r2v.editorReferencesChanged", {
                  defaultValue:
                    "引用图片或编辑对象已变化。为避免引用到错误图片，请重新载入后继续编辑。当前编辑暂时保留。",
                })
              : t("r2v.editorChangedDescription", {
                  defaultValue:
                    "当前编辑暂时保留。请选择重新载入最新内容，或明确保留您的编辑后再完成。",
                })
          }
          action={
            <div className="flex flex-wrap gap-2">
              <Button size="small" data-prompt-editor-reload onClick={reload}>
                {t("r2v.editorReload", { defaultValue: "重新载入最新内容" })}
              </Button>
              <Button
                size="small"
                data-prompt-editor-keep
                disabled={referencesChanged || scopeChanged}
                onClick={() => {
                  if (referencesChanged || scopeChanged) return;
                  setBaseline((current) => ({
                    ...current,
                    sourceValue,
                    presentedValue: initialValue,
                  }));
                }}
              >
                {t("r2v.editorKeep", { defaultValue: "保留我的编辑" })}
              </Button>
            </div>
          }
        />
      )}
      {/* Constant editor height: neither the prompt length nor the number of
          addable assets may grow the modal. */}
      <div className="flex h-[min(62vh,600px)] min-h-[400px] gap-3">
        <PromptTokenEditor
          key={editorRevision}
          ref={editorRef}
          initialValue={editorSeed}
          tokens={allTokens}
          disabled={disabled}
          onChange={setDraft}
        />
        {(allTokens.length > 0 || candidates.length > 0) && (
          <div className="flex w-[210px] shrink-0 flex-col rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-2.5">
            <p className="text-[10.5px] font-bold text-[var(--color-text-secondary)]">
              {t("r2v.insertRefTitle")}
            </p>
            <p className="mb-2 mt-0.5 text-[9.5px] leading-relaxed text-[var(--color-text-tertiary)]">
              {t("r2v.insertRefHint")}
            </p>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {allTokens.map((token) => (
                <button
                  key={`token-${token.index}-${allTokens.indexOf(token)}`}
                  type="button"
                  disabled={
                    disabled ||
                    conflict ||
                    !promptTokenAt(allTokens, token.index)
                  }
                  onClick={() => editorRef.current?.insertToken(token.index)}
                  className="mb-1.5 flex w-full items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-left transition-colors hover:border-[var(--color-accent)]"
                >
                  {promptTokenAt(allTokens, token.index)?.thumbUrl ? (
                    <img
                      src={token.thumbUrl}
                      alt=""
                      className="h-6 w-8 rounded border border-[var(--color-border)] object-cover"
                    />
                  ) : (
                    <span className="flex h-6 w-8 items-center justify-center rounded border border-dashed border-[var(--color-border)] font-mono text-[8px] text-[var(--color-text-tertiary)]">
                      {token.index}
                    </span>
                  )}
                  <span className="min-w-0 flex-1 truncate text-[10.5px]">
                    <b className="font-mono text-[9px] text-[var(--color-accent)]">
                      {`[${token.index}]`}
                    </b>{" "}
                    {promptTokenAt(allTokens, token.index)
                      ? token.name
                      : t("r2v.tokenMissing", { index: token.index })}
                  </span>
                </button>
              ))}
            </div>
            {openCandidates.length > 0 && (
              <button
                type="button"
                data-prompt-add-reference
                disabled={disabled || conflict}
                onClick={() => setPickerOpen(true)}
                className="mt-2 flex w-full shrink-0 items-center justify-center gap-1 rounded-lg border border-dashed border-[var(--color-border-strong)] px-2 py-1.5 text-[10.5px] font-medium text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
              >
                <Plus className="h-3 w-3" />
                {t("r2v.addReference")}
              </button>
            )}
          </div>
        )}
      </div>
      <RelatedAssetPicker
        open={pickerOpen}
        candidates={openCandidates.map((candidate) => ({
          id: candidate.id,
          kind: candidate.kind ?? "material",
          name: candidate.name,
          thumbUrl: candidate.thumbUrl,
        }))}
        boundIds={[]}
        onCancel={() => setPickerOpen(false)}
        onConfirm={(selectedIds) => {
          setPickerOpen(false);
          addCandidates(selectedIds);
        }}
      />
    </Modal>
  );
}

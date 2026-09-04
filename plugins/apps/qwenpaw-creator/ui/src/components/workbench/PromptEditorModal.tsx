import { useEffect, useRef, useState } from "react";
import { Button, Modal } from "antd";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import PromptTokenEditor, {
  type PromptTokenEditorHandle,
} from "@/components/workbench/PromptTokenEditor";
import type { PromptRichToken } from "@/components/workbench/PromptRichBlock";
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
  tokens,
  candidates = [],
  disabled = false,
  onCancel,
  onDone,
}: {
  open: boolean;
  label: string;
  initialValue: string;
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
  useEffect(() => {
    if (!open) return;
    setDraft(initialValue);
    setAdded([]);
    setPickerOpen(false);
    // initialValue is sampled when the modal opens; edits stay local.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const allTokens = [...tokens, ...added];
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
    let index = allTokens.reduce((max, token) => Math.max(max, token.index), 0);
    const newTokens = picked.map((candidate) => {
      index += 1;
      return {
        candidateId: candidate.id,
        index,
        name: candidate.name,
        kind: "artifact" as const,
        thumbUrl: candidate.thumbUrl,
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
            disabled={disabled}
            data-prompt-editor-done
            onClick={() =>
              onDone(
                draft,
                added.map((token) => token.candidateId),
              )
            }
          >
            {t("r2v.fullscreenDone")}
          </Button>
        </div>
      }
      destroyOnHidden
    >
      {/* Constant editor height: neither the prompt length nor the number of
          addable assets may grow the modal. */}
      <div className="flex h-[min(62vh,600px)] min-h-[400px] gap-3">
        <PromptTokenEditor
          ref={editorRef}
          initialValue={initialValue}
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
                  key={`token-${token.index}`}
                  type="button"
                  onClick={() => editorRef.current?.insertToken(token.index)}
                  className="mb-1.5 flex w-full items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-left transition-colors hover:border-[var(--color-accent)]"
                >
                  {token.thumbUrl ? (
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
                    {token.name}
                  </span>
                </button>
              ))}
            </div>
            {openCandidates.length > 0 && (
              <button
                type="button"
                data-prompt-add-reference
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

import {
  ChevronDown,
  ChevronUp,
  EyeOff,
  LoaderCircle,
  Plus,
} from "lucide-react";
import type { TFunction } from "i18next";

import { ProviderIcon } from "../../Settings/Models/components/ProviderIconComponent";
import type { CandidateModel } from "./modelSelectorModels";
import { modelKey } from "./modelSelectorModels";
import styles from "./index.module.less";

interface CandidateModelSectionProps {
  candidates: CandidateModel[];
  expanded: boolean;
  controlsId: string;
  searchActive: boolean;
  addingKey: string | null;
  visibilityKey: string | null;
  t: TFunction;
  onToggle: () => void;
  onAdd: (candidate: CandidateModel) => void;
  onHide: (candidate: CandidateModel) => void;
}

export function CandidateModelSection({
  candidates,
  expanded,
  controlsId,
  searchActive,
  addingKey,
  visibilityKey,
  t,
  onToggle,
  onAdd,
  onHide,
}: CandidateModelSectionProps) {
  if (candidates.length === 0) return null;

  return (
    <div className={styles.candidateModelSection}>
      <button
        type="button"
        className={styles.candidateSectionToggle}
        aria-expanded={expanded}
        aria-controls={controlsId}
        disabled={searchActive}
        onClick={onToggle}
      >
        <Plus size={14} />
        <span className={styles.candidateSectionTitle}>
          {t("modelSelector.availableToAdd")}
        </span>
        <span className={styles.candidateSectionMeta}>
          {candidates.length}
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </button>
      {expanded && (
        <div id={controlsId} className={styles.candidateSectionBody}>
          {candidates.map((candidate) => {
            const key = modelKey(candidate.provider.id, candidate.model.id);
            return (
              <div key={key} className={styles.candidateItem}>
                <div className={styles.candidateIdentity}>
                  <ProviderIcon providerId={candidate.provider.id} size={16} />
                  <span title={candidate.model.name || candidate.model.id}>
                    {candidate.model.name || candidate.model.id}
                  </span>
                </div>
                <button
                  type="button"
                  className={styles.candidateSecondaryButton}
                  aria-label={t("modelSelector.hideModel")}
                  disabled={visibilityKey === key}
                  onClick={() => onHide(candidate)}
                >
                  <EyeOff size={14} />
                </button>
                <button
                  type="button"
                  className={styles.addCandidateButton}
                  aria-label={t("modelSelector.addAndUse")}
                  disabled={addingKey === key}
                  onClick={() => onAdd(candidate)}
                >
                  {addingKey === key ? (
                    <LoaderCircle size={14} className={styles.spinning} />
                  ) : (
                    <Plus size={14} />
                  )}
                  {t("modelSelector.addAndUse")}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

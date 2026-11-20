import { useState } from "react";
import { Popover } from "radix-ui";
import { Plus, RotateCcw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { normalizeWeights, type BenchmarkWeights } from "./types";

export default function BenchmarkWeightsEditor({
  benchmarks,
  domains,
  defaults,
  value,
  onApply,
}: {
  benchmarks: Record<string, string>;
  domains: Record<string, string>;
  defaults: BenchmarkWeights;
  value: BenchmarkWeights | null;
  onApply: (weights: BenchmarkWeights | null) => void;
}) {
  const { t, i18n } = useTranslation("evaluation");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const current = value ?? defaults;
  const selected = Object.keys(current);
  const available = Object.keys(defaults).filter((id) => !(id in current));
  const percent = (weight: number) =>
    new Intl.NumberFormat(i18n.language, {
      style: "percent",
      maximumFractionDigits: 1,
    }).format(weight);
  const apply = (weights: BenchmarkWeights) => {
    const normalized = normalizeWeights(weights);
    const preset =
      Object.keys(defaults).length === Object.keys(normalized).length &&
      Object.entries(defaults).every(
        ([id, weight]) => Math.abs(weight - (normalized[id] ?? 0)) < 0.00001,
      );
    onApply(preset ? null : normalized);
    setEditing(null);
  };
  const valid =
    draft.trim() !== "" &&
    Number.isFinite(Number(draft)) &&
    Number(draft) > 0 &&
    Number(draft) < 100;
  const setShare = (id: string, share: number) => {
    const keys = id in current ? selected : [...selected, id];
    apply(
      Object.fromEntries(
        keys.map((key) => [
          key,
          key === id
            ? share
            : (current[key] / (1 - (current[id] ?? 0))) * (1 - share),
        ]),
      ),
    );
  };
  return (
    <div className="evaluation-weight-control" aria-label={t("benchmarkSet")}>
      <div className="evaluation-benchmark-tabs">
        {selected.map((id) => (
          <div
            className="evaluation-benchmark-tab"
            data-editing={editing === id}
            key={id}
          >
            <Popover.Root
              open={editing === id}
              onOpenChange={(open) => {
                setEditing(open ? id : null);
                if (open)
                  setDraft(String(Number((current[id] * 100).toFixed(3))));
              }}
            >
              <Popover.Trigger asChild>
                <button type="button" className="evaluation-tab-edit">
                  <small>{t(`domains.${domains[id]}`)}</small>
                  <span>{benchmarks[id]}</span>
                  <b>{percent(current[id])}</b>
                </button>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  className="evaluation-weight-panel"
                  align="start"
                  sideOffset={8}
                  collisionPadding={12}
                  aria-label={t("editShare", { benchmark: benchmarks[id] })}
                >
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      if (selected.length > 1 && valid)
                        setShare(id, Number(draft) / 100);
                    }}
                  >
                    <header>
                      <h2>{benchmarks[id]}</h2>
                      <Popover.Close aria-label={t("closeWeights")}>
                        <X size={16} />
                      </Popover.Close>
                    </header>
                    <label className="evaluation-share-input">
                      {t("effectiveWeight")}
                      <input
                        type="number"
                        min="0"
                        max="100"
                        step="any"
                        inputMode="decimal"
                        value={draft}
                        disabled={selected.length === 1}
                        onChange={(event) => setDraft(event.target.value)}
                      />
                      <span>%</span>
                    </label>
                    <p>
                      {t(
                        selected.length === 1
                          ? "singleBenchmarkWeight"
                          : "shareHelp",
                      )}
                    </p>
                    {selected.length > 1 && (
                      <div className="evaluation-weight-footer">
                        <span role="status">{!valid && t("invalidShare")}</span>
                        <button
                          type="submit"
                          className="evaluation-weight-apply"
                          disabled={!valid}
                        >
                          {t("applyWeights")}
                        </button>
                      </div>
                    )}
                  </form>
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
            <button
              type="button"
              className="evaluation-tab-close"
              aria-label={t("removeBenchmark", { benchmark: benchmarks[id] })}
              title={
                selected.length === 1
                  ? t("keepOneBenchmark")
                  : t("removeBenchmark", { benchmark: benchmarks[id] })
              }
              disabled={selected.length === 1}
              onClick={() =>
                apply(
                  Object.fromEntries(
                    Object.entries(current).filter(([key]) => key !== id),
                  ),
                )
              }
            >
              <X size={14} />
            </button>
          </div>
        ))}
        <Popover.Root>
          <Popover.Trigger asChild>
            <button
              type="button"
              className="evaluation-tab-add"
              aria-label={t("addBenchmark")}
              title={t("addBenchmark")}
              disabled={!available.length}
            >
              <Plus size={18} />
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content
              className="evaluation-weight-panel evaluation-benchmark-add"
              align="end"
              sideOffset={8}
              collisionPadding={12}
              aria-label={t("addBenchmark")}
            >
              <h2>{t("addBenchmark")}</h2>
              {available.map((id) => (
                <Popover.Close asChild key={id}>
                  <button
                    type="button"
                    onClick={() => setShare(id, defaults[id])}
                  >
                    <span>
                      <small>{t(`domains.${domains[id]}`)}</small>
                      {benchmarks[id]}
                    </span>
                    <Plus size={16} />
                  </button>
                </Popover.Close>
              ))}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      </div>
      {value !== null && (
        <button
          type="button"
          className="evaluation-weight-reset"
          onClick={() => onApply(null)}
        >
          <RotateCcw size={14} />
          {t("resetWeights")}
        </button>
      )}
    </div>
  );
}

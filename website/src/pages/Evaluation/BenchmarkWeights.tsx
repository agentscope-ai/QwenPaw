import { useEffect, useState, type ReactNode } from "react";
import { Dialog, Popover } from "radix-ui";
import { CircleHelp, Pencil, RotateCcw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { normalizeWeights, type BenchmarkWeights } from "./types";

export default function BenchmarkWeightsEditor({
  benchmarks,
  defaults,
  value,
  onApply,
}: {
  benchmarks: Record<string, string>;
  defaults: BenchmarkWeights;
  value: BenchmarkWeights | null;
  onApply: (weights: BenchmarkWeights | null) => void;
}) {
  const { t, i18n } = useTranslation("evaluation");
  const [open, setOpen] = useState(false);
  const [mobile, setMobile] = useState(
    () => window.matchMedia("(max-width: 700px)").matches,
  );
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string[]>([]);
  const current = value ?? defaults;
  const percent = (weight: number) =>
    new Intl.NumberFormat(i18n.language, {
      style: "percent",
      maximumFractionDigits: 1,
    }).format(weight);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 700px)");
    const update = () => setMobile(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  const reset = (weights: BenchmarkWeights) => {
    setSelected(Object.keys(weights));
    setDraft(
      Object.fromEntries(
        Object.keys(defaults).map((id) => [
          id,
          String(Number(((weights[id] ?? defaults[id]) * 100).toFixed(3))),
        ]),
      ),
    );
  };
  const changeOpen = (next: boolean) => {
    if (next) reset(current);
    setOpen(next);
  };
  const valid =
    selected.length > 0 &&
    selected.every(
      (id) =>
        draft[id]?.trim() !== "" &&
        Number.isFinite(Number(draft[id])) &&
        Number(draft[id]) > 0,
    ) &&
    Number.isFinite(selected.reduce((sum, id) => sum + Number(draft[id]), 0));
  const normalized = valid
    ? normalizeWeights(
        Object.fromEntries(selected.map((id) => [id, Number(draft[id])])),
      )
    : {};
  const apply = () => {
    if (!valid) return;
    const preset =
      Object.keys(defaults).length === selected.length &&
      Object.entries(defaults).every(
        ([id, weight]) => Math.abs(weight - (normalized[id] ?? 0)) < 0.00001,
      );
    onApply(preset ? null : normalized);
    setOpen(false);
  };
  const trigger = (
    <button
      type="button"
      className="evaluation-weight-trigger"
      disabled={!Object.keys(defaults).length}
    >
      <span>
        {t("benchmarkSet")} ·{" "}
        {t("selectedBenchmarks", { count: Object.keys(current).length })}
      </span>
      <Pencil size={14} aria-hidden="true" />
      {t("editWeights")}
    </button>
  );
  const summary = (
    <div className="evaluation-weight-summary" aria-live="polite">
      <strong>{t(value === null ? "presetWeights" : "customWeights")}</strong>
      {Object.entries(current).map(([id, weight]) => (
        <span key={id}>
          {benchmarks[id]} <b>{percent(weight)}</b>
        </span>
      ))}
    </div>
  );
  const body = (
    <>
      <div className="evaluation-weight-heading">
        <span>{t("relativeWeight")}</span>
        <Popover.Root>
          <Popover.Trigger asChild>
            <button type="button" aria-label={t("weightsHelpLabel")}>
              <CircleHelp size={16} />
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content
              className="evaluation-methodology-tooltip"
              sideOffset={6}
              collisionPadding={12}
            >
              {t("weightsHelp")}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
        <span>{t("effectiveWeight")}</span>
      </div>
      <div className="evaluation-weight-rows">
        {Object.keys(defaults).map((id) => (
          <div className="evaluation-weight-row" key={id}>
            <label>
              <input
                type="checkbox"
                checked={selected.includes(id)}
                onChange={(event) =>
                  setSelected((ids) =>
                    event.target.checked
                      ? [...ids, id]
                      : ids.filter((value) => value !== id),
                  )
                }
              />
              <span>{benchmarks[id]}</span>
            </label>
            <input
              type="number"
              min="0"
              step="any"
              inputMode="decimal"
              aria-label={`${t("relativeWeight")} · ${benchmarks[id]}`}
              value={draft[id] ?? ""}
              disabled={!selected.includes(id)}
              onChange={(event) =>
                setDraft((values) => ({ ...values, [id]: event.target.value }))
              }
            />
            <output>
              {selected.includes(id) && valid ? percent(normalized[id]) : "—"}
            </output>
          </div>
        ))}
      </div>
      <div className="evaluation-weight-footer">
        <button type="button" onClick={() => reset(defaults)}>
          <RotateCcw size={15} />
          {t("resetWeights")}
        </button>
        <span
          className={valid ? "" : "evaluation-weight-error"}
          role={valid ? undefined : "status"}
        >
          {valid ? t("weightTotal") : t("invalidWeights")}
        </span>
        <button
          className="evaluation-weight-apply"
          type="submit"
          disabled={!valid}
        >
          {t("applyWeights")}
        </button>
      </div>
    </>
  );
  const close = (
    <button
      type="button"
      aria-label={t("closeWeights")}
      onClick={() => setOpen(false)}
    >
      <X size={18} />
    </button>
  );
  const form = (title: ReactNode) => (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        apply();
      }}
    >
      <header>
        {title}
        {close}
      </header>
      {body}
    </form>
  );
  return (
    <div className="evaluation-weight-control">
      {mobile ? (
        <Dialog.Root open={open} onOpenChange={changeOpen}>
          <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay className="evaluation-weight-overlay" />
            <Dialog.Content
              className="evaluation-weight-panel evaluation-weight-sheet"
              aria-describedby={undefined}
            >
              {form(<Dialog.Title>{t("editBenchmarks")}</Dialog.Title>)}
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      ) : (
        <Popover.Root open={open} onOpenChange={changeOpen}>
          <Popover.Trigger asChild>{trigger}</Popover.Trigger>
          <Popover.Portal>
            <Popover.Content
              className="evaluation-weight-panel"
              align="start"
              sideOffset={8}
              collisionPadding={12}
              aria-label={t("editBenchmarks")}
            >
              {form(<h2>{t("editBenchmarks")}</h2>)}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      )}
      {summary}
    </div>
  );
}

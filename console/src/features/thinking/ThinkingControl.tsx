import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { InputNumber, Slider, Tooltip } from "antd";
import NumberFlow from "@number-flow/react";
import { LockKeyhole, RotateCcw, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ThinkingControlSpec, ThinkingPreference } from "./types";
import styles from "./thinking.module.less";

export function ThinkingControl({
  control,
  value,
  onChange,
  onPreview,
  disabled = false,
  modelLabel,
  onChooseModel,
  resetAction,
  effective,
}: {
  control: ThinkingControlSpec;
  value: ThinkingPreference;
  onChange: (value: ThinkingPreference) => void;
  onPreview?: (value: ThinkingPreference) => void;
  disabled?: boolean;
  modelLabel?: ReactNode;
  onChooseModel?: () => void;
  resetAction?: ReactNode;
  effective?: ThinkingPreference;
}) {
  const { t } = useTranslation();
  const displayed = value.level === "inherit" ? effective ?? value : value;
  const efforts = control.supports_off
    ? ["off" as const, ...control.efforts.filter((level) => level !== "off")]
    : control.efforts;
  const low = control.budget_min ?? 1;
  const high = control.budget_max ?? low;
  const offPosition = low - Math.max(1, Math.round((high - low) * 0.12));
  const [editingBudget, setEditingBudget] = useState(false);
  const initial = Math.min(
    high,
    Math.max(low, displayed.budget_tokens ?? control.budget_default ?? low),
  );
  const [budget, setBudget] = useState(initial);
  useEffect(() => setBudget(initial), [initial]);
  const isBudget = control.kind === "budget";
  const unsupported =
    control.kind === "unsupported" || control.kind === "unknown";
  const [effortIndex, setEffortIndex] = useState(
    Math.max(0, efforts.indexOf(displayed.level)),
  );
  const [adjusting, setAdjusting] = useState(false);
  useEffect(() => {
    setEffortIndex(Math.max(0, efforts.indexOf(displayed.level)));
    setAdjusting(false);
  }, [displayed.level, control]);
  const unresolved = displayed.level === "inherit" && !adjusting;
  const ratio = isBudget
    ? Math.min(1, Math.max(0, (budget - low) / Math.max(1, high - low)))
    : effortIndex / Math.max(1, efforts.length - 1);
  const band =
    ratio < 0.25
      ? "light"
      : ratio < 0.6
      ? "balanced"
      : ratio < 0.85
      ? "deep"
      : "intensive";
  const label = unresolved
    ? null
    : isBudget && adjusting && budget < low
    ? t("thinkingControl.off")
    : displayed.level === "budget" || (isBudget && adjusting)
    ? t(`thinkingControl.${band}`)
    : t(
        `thinkingControl.${adjusting ? efforts[effortIndex] : displayed.level}`,
      );
  function commitBudget(next: number) {
    const bounded = Math.min(high, Math.max(low, Math.round(next)));
    setBudget(bounded);
    setAdjusting(false);
    onChange({ level: "budget", budget_tokens: bounded });
  }
  return (
    <section
      className={styles.control}
      data-budget-off={isBudget && control.supports_off}
      data-unresolved={unresolved}
      style={
        {
          "--thinking-pigment": `color-mix(in srgb, var(--thinking-${
            ratio < 0.5 ? "start" : "mid"
          }), var(--thinking-${ratio < 0.5 ? "mid" : "end"}) ${Math.round(
            (ratio < 0.5 ? ratio * 2 : (ratio - 0.5) * 2) * 100,
          )}%)`,
          "--thinking-low-position": `${
            ((low - offPosition) / (high - offPosition)) * 100
          }%`,
        } as CSSProperties
      }
      onKeyDownCapture={(event) => {
        if (
          !disabled &&
          unresolved &&
          !unsupported &&
          (event.target as HTMLElement).getAttribute("role") === "slider" &&
          [
            "ArrowLeft",
            "ArrowRight",
            "ArrowUp",
            "ArrowDown",
            "Home",
            "End",
          ].includes(event.key)
        ) {
          event.preventDefault();
          event.stopPropagation();
          const last = event.key === "End";
          if (isBudget) commitBudget(last ? high : low);
          else
            onChange({
              level: last ? efforts[efforts.length - 1] : efforts[0],
            });
          return;
        }
        if (
          disabled ||
          !isBudget ||
          !control.supports_off ||
          (event.target as HTMLElement).getAttribute("role") !== "slider"
        )
          return;
        const off = adjusting ? budget < low : displayed.level === "off";
        const increase = ["ArrowRight", "ArrowUp"].includes(event.key);
        const decrease = ["ArrowLeft", "ArrowDown"].includes(event.key);
        // The visual gap is not a range of valid budget values.
        if ((off && increase) || (!off && budget === low && decrease)) {
          event.preventDefault();
          event.stopPropagation();
          if (off) commitBudget(low);
          else {
            setBudget(offPosition);
            setAdjusting(false);
            onChange({ level: "off" });
          }
        }
      }}
    >
      <header className={styles.header}>
        <div className={styles.budgetSlot}>
          {isBudget &&
            !unresolved &&
            (editingBudget ? (
              <InputNumber
                autoFocus
                aria-label={t("thinkingControl.budget")}
                value={budget}
                min={low}
                max={high}
                precision={0}
                step={1}
                disabled={disabled}
                onChange={(next) => {
                  if (next !== null) {
                    setBudget(next);
                    setAdjusting(true);
                    onPreview?.({ level: "budget", budget_tokens: next });
                  }
                }}
                onBlur={() => {
                  if (adjusting) commitBudget(budget);
                  setEditingBudget(false);
                }}
                onPressEnter={() => {
                  if (adjusting) commitBudget(budget);
                  setEditingBudget(false);
                }}
              />
            ) : (
              <button
                type="button"
                className={styles.budgetValue}
                aria-label={t("thinkingControl.budget")}
                disabled={disabled}
                onClick={() => setEditingBudget(true)}
              >
                <NumberFlow
                  value={
                    (adjusting ? budget < low : displayed.level === "off")
                      ? 0
                      : Math.max(low, budget)
                  }
                  transformTiming={{ duration: 180, easing: "ease-out" }}
                  opacityTiming={{ duration: 100, easing: "ease-out" }}
                  respectMotionPreference
                  format={{ notation: "compact", maximumFractionDigits: 1 }}
                  locales="en"
                />
              </button>
            ))}
        </div>
        <div className={styles.identity}>
          {onChooseModel ? (
            <button
              type="button"
              className={styles.modelChoice}
              onClick={onChooseModel}
              aria-label={
                unsupported || unresolved
                  ? t("modelSelector.selectModel")
                  : undefined
              }
            >
              <strong>
                {!unsupported && label}
                <ChevronRight size={14} aria-hidden="true" />
              </strong>
              <span
                title={typeof modelLabel === "string" ? modelLabel : undefined}
              >
                {modelLabel}
              </span>
            </button>
          ) : (
            <strong>{label}</strong>
          )}
        </div>
        <div className={styles.resetSlot}>
          {resetAction ??
            (!unsupported && (
              <Tooltip title={t("thinkingControl.reset")}>
                <button
                  type="button"
                  className={styles.iconButton}
                  disabled={disabled || value.level === "inherit"}
                  aria-label={t("thinkingControl.reset")}
                  onClick={() => onChange({ level: "inherit" })}
                >
                  <RotateCcw size={15} />
                </button>
              </Tooltip>
            ))}
        </div>
      </header>
      {unsupported ? (
        <Tooltip
          trigger={["hover", "focus", "click"]}
          title={t(
            control.kind === "unknown"
              ? "thinkingControl.unknown"
              : "thinkingControl.unsupported",
          )}
        >
          <div
            className={styles.staticRail}
            tabIndex={0}
            role="img"
            aria-label={t(
              control.kind === "unknown"
                ? "thinkingControl.unknown"
                : "thinkingControl.unsupported",
            )}
          >
            <LockKeyhole size={12} />
          </div>
        </Tooltip>
      ) : (
        <>
          <Slider
            ariaLabelForHandle={t("thinkingControl.title")}
            disabled={disabled || (!isBudget && efforts.length < 2)}
            ariaValueTextFormatterForHandle={(next) =>
              unresolved
                ? t("thinkingControl.inherit")
                : isBudget
                ? next < low
                  ? t("thinkingControl.off")
                  : `${next.toLocaleString()} tokens`
                : t(`thinkingControl.${efforts[next]}`)
            }
            min={isBudget ? (control.supports_off ? offPosition : low) : 0}
            max={isBudget ? high : Math.max(1, efforts.length - 1)}
            step={isBudget ? 1 : null}
            value={
              isBudget
                ? displayed.level === "off" && !adjusting
                  ? offPosition
                  : budget
                : effortIndex
            }
            marks={
              isBudget && control.supports_off
                ? Object.fromEntries([
                    [offPosition, " "],
                    ...Array.from({ length: 4 }, (_, index) => [
                      Math.round(low + ((high - low) * index) / 3),
                      " ",
                    ]),
                  ])
                : isBudget
                ? Object.fromEntries(
                    Array.from({ length: 5 }, (_, index) => [
                      Math.round(low + ((high - low) * index) / 4),
                      " ",
                    ]),
                  )
                : Object.fromEntries(efforts.map((_, index) => [index, " "]))
            }
            tooltip={{ open: false }}
            onChange={(next) => {
              setAdjusting(true);
              onPreview?.(
                isBudget
                  ? next < (low + offPosition) / 2
                    ? { level: "off" }
                    : { level: "budget", budget_tokens: Math.max(low, next) }
                  : { level: efforts[next] },
              );
              if (isBudget)
                setBudget(
                  next < low
                    ? next < (low + offPosition) / 2
                      ? offPosition
                      : low
                    : next,
                );
              else setEffortIndex(next);
            }}
            onChangeComplete={(next) => {
              setAdjusting(false);
              if (isBudget && next < (low + offPosition) / 2)
                onChange({ level: "off" });
              else if (isBudget) commitBudget(next as number);
              else onChange({ level: efforts[next as number] });
            }}
          />
        </>
      )}
    </section>
  );
}

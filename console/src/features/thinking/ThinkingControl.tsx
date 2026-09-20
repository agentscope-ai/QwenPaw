import { useEffect, useState, type CSSProperties } from "react";
import { InputNumber, Slider, Tooltip } from "antd";
import { Brain, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ThinkingControlSpec, ThinkingPreference } from "./types";
import styles from "./thinking.module.less";

export function ThinkingControl({
  control,
  value,
  onChange,
  disabled = false,
}: {
  control: ThinkingControlSpec;
  value: ThinkingPreference;
  onChange: (value: ThinkingPreference) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const low = control.budget_min ?? 1;
  const high = control.budget_max ?? low;
  const initial = Math.min(
    high,
    Math.max(low, value.budget_tokens ?? control.budget_default ?? low),
  );
  const [budget, setBudget] = useState(initial);
  useEffect(() => setBudget(initial), [initial]);
  const isBudget = control.kind === "budget";
  const unsupported =
    control.kind === "unsupported" || control.kind === "unknown";
  const [effortIndex, setEffortIndex] = useState(
    Math.max(0, control.efforts.indexOf(value.level)),
  );
  const [adjusting, setAdjusting] = useState(false);
  useEffect(() => {
    setEffortIndex(Math.max(0, control.efforts.indexOf(value.level)));
    setAdjusting(false);
  }, [value.level, control]);
  const ratio = isBudget
    ? (budget - low) / Math.max(1, high - low)
    : effortIndex / Math.max(1, control.efforts.length - 1);
  const band =
    ratio < 0.25
      ? "light"
      : ratio < 0.6
      ? "balanced"
      : ratio < 0.85
      ? "deep"
      : "intensive";
  const color = `hsl(27 92% ${66 - ratio * 27}%)`;
  const label =
    value.level === "budget" || (isBudget && adjusting)
      ? t(`thinkingControl.${band}`)
      : t(
          `thinkingControl.${
            adjusting ? control.efforts[effortIndex] : value.level
          }`,
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
      style={{ "--thinking-color": color } as CSSProperties}
    >
      <header className={styles.header}>
        <span>
          <Brain size={16} strokeWidth={1.7} />
          {t("thinkingControl.title")}
        </span>
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
      </header>
      {unsupported ? (
        <p className={styles.hint}>
          {t(
            control.kind === "unknown"
              ? "thinkingControl.unknown"
              : "thinkingControl.unsupported",
          )}
        </p>
      ) : (
        <>
          <div className={styles.summary}>
            <strong>{label}</strong>
            {isBudget && (
              <InputNumber
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
                  }
                }}
                onBlur={() => {
                  if (adjusting) commitBudget(budget);
                }}
                onPressEnter={() => {
                  if (adjusting) commitBudget(budget);
                }}
                suffix="tokens"
              />
            )}
          </div>
          <Slider
            ariaLabelForHandle={t("thinkingControl.title")}
            disabled={disabled || (!isBudget && control.efforts.length < 2)}
            min={isBudget ? low : 0}
            max={isBudget ? high : Math.max(1, control.efforts.length - 1)}
            step={1}
            value={isBudget ? budget : effortIndex}
            dots={!isBudget}
            tooltip={{
              formatter: (next) =>
                isBudget
                  ? `${next?.toLocaleString()} tokens`
                  : t(`thinkingControl.${control.efforts[next ?? 0]}`),
            }}
            onChange={(next) => {
              setAdjusting(true);
              if (isBudget) setBudget(next);
              else setEffortIndex(next);
            }}
            onChangeComplete={(next) => {
              setAdjusting(false);
              if (isBudget) commitBudget(next as number);
              else onChange({ level: control.efforts[next as number] });
            }}
          />
          <div className={styles.range}>
            <span>
              {isBudget
                ? low.toLocaleString()
                : t(`thinkingControl.${control.efforts[0]}`)}
            </span>
            <span>
              {isBudget
                ? high.toLocaleString()
                : t(
                    `thinkingControl.${
                      control.efforts[control.efforts.length - 1]
                    }`,
                  )}
            </span>
          </div>
          <div className={styles.modes}>
            <button
              type="button"
              disabled={disabled}
              aria-pressed={value.level === "inherit"}
              onClick={() => onChange({ level: "inherit" })}
            >
              {t("thinkingControl.inherit")}
            </button>
            {control.supports_off && (
              <button
                type="button"
                disabled={disabled}
                aria-pressed={value.level === "off"}
                onClick={() => onChange({ level: "off" })}
              >
                {t("thinkingControl.off")}
              </button>
            )}
          </div>
          <p className={styles.hint}>
            {t(
              isBudget
                ? "thinkingControl.budgetHint"
                : "thinkingControl.effortHint",
            )}
          </p>
        </>
      )}
    </section>
  );
}

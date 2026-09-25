import { InputNumber, type InputNumberProps } from "antd";
import { Minus, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { motion, useReducedMotion } from "motion/react";
import styles from "./NumberStepper.module.less";

/** A bounded stepper that retains direct numeric entry and Form semantics. */
export function NumberStepper({
  value,
  onChange,
  min,
  max,
  step = 1,
  disabled,
  style,
  ...props
}: InputNumberProps<number>) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const adjust = (direction: number) => {
    const next = Number(
      ((value ?? min ?? 0) + direction * Number(step)).toFixed(8),
    );
    onChange?.(Math.min(max ?? Infinity, Math.max(min ?? -Infinity, next)));
  };
  return (
    <div
      className={styles.stepper}
      style={style}
      data-disabled={disabled || undefined}
    >
      <motion.button
        type="button"
        aria-label={t("common.decrease")}
        disabled={disabled || (value != null && min != null && value <= min)}
        onClick={() => adjust(-1)}
        whileTap={reduced ? undefined : { scale: 0.92 }}
      >
        <Minus size={16} />
      </motion.button>
      <InputNumber
        {...props}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={onChange}
        disabled={disabled}
        controls={false}
        variant="borderless"
      />
      <motion.button
        type="button"
        aria-label={t("common.increase")}
        disabled={disabled || (value != null && max != null && value >= max)}
        onClick={() => adjust(1)}
        whileTap={reduced ? undefined : { scale: 0.92 }}
      >
        <Plus size={16} />
      </motion.button>
    </div>
  );
}

import { InputNumber, Slider } from "antd";
import { useState } from "react";
import NumberFlow from "@number-flow/react";
import styles from "./NumberSlider.module.less";

/** A direct control with a precise value for keyboard users. */
export function NumberSlider({
  value,
  onChange,
  min = 0,
  max = 1000,
  step = 1,
  label,
}: {
  value?: number;
  onChange?: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  label?: string;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <div className={styles.control}>
      <Slider
        aria-label={label}
        style={{ flex: 1, minWidth: 70 }}
        min={min}
        max={Math.max(max, value ?? min)}
        step={step}
        value={value}
        onChange={onChange}
      />
      {editing ? (
        <InputNumber
          autoFocus
          onBlur={() => setEditing(false)}
          onPressEnter={() => setEditing(false)}
          aria-label={label}
          style={{ width: 84, flexShrink: 0 }}
          min={min}
          step={step}
          value={value}
          onChange={(next) => {
            if (typeof next === "number") onChange?.(next);
          }}
        />
      ) : (
        <button
          type="button"
          className={styles.value}
          aria-label={label}
          onClick={() => setEditing(true)}
        >
          <NumberFlow
            value={value ?? min}
            respectMotionPreference
            transformTiming={{ duration: 180, easing: "ease-out" }}
            format={{ maximumFractionDigits: 6, useGrouping: false }}
          />
        </button>
      )}
    </div>
  );
}

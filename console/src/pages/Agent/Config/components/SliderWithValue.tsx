import { Slider } from "@agentscope-ai/design";
import NumberFlow from "@number-flow/react";
import styles from "@/components/interaction/NumberSlider.module.less";

interface SliderWithValueProps {
  value?: number;
  min?: number;
  max?: number;
  step?: number;
  marks?: Record<number, string>;
  onChange?: (value: number) => void;
}

export function SliderWithValue({
  value,
  min,
  max,
  step,
  marks,
  onChange,
}: SliderWithValueProps) {
  return (
    <div className={styles.control}>
      <div style={{ flex: 1 }}>
        <Slider
          value={value}
          min={min}
          max={max}
          step={step}
          marks={marks}
          onChange={onChange}
        />
      </div>
      <div style={{ minWidth: 50, textAlign: "right", lineHeight: "32px" }}>
        <span className={styles.value}>
          {value !== undefined ? (
            <NumberFlow
              value={value}
              respectMotionPreference
              transformTiming={{ duration: 180, easing: "ease-out" }}
              format={{
                minimumFractionDigits: value < 1 ? 2 : 0,
                maximumFractionDigits: 6,
                useGrouping: false,
              }}
            />
          ) : (
            "-"
          )}
        </span>
      </div>
    </div>
  );
}

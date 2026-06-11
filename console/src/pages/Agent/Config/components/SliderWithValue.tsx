import { Slider } from "@/components/ui/slider";
import styles from "../index.module.less";

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
  min = 0,
  max = 100,
  step = 1,
  onChange,
}: SliderWithValueProps) {
  const formatValue = (v: number) => {
    if (v >= 1) return v.toString();
    return v.toFixed(2);
  };

  return (
    <div className="flex items-center gap-4">
      <div className="flex-1">
        <Slider
          value={value !== undefined ? [value] : undefined}
          min={min}
          max={max}
          step={step}
          onValueChange={(vals) => onChange?.(vals[0])}
        />
      </div>
      <div className="min-w-[50px] text-right leading-8">
        <span className={styles.sliderValue}>
          {value !== undefined ? formatValue(value) : "-"}
        </span>
      </div>
    </div>
  );
}

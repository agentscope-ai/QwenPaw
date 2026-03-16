import { Slider } from "@agentscope-ai/design";

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
  const formatValue = (v: number) => {
    if (v >= 1) return v.toString();
    return v.toFixed(2);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
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
        <span style={{ fontWeight: 500, color: "#1890ff" }}>
          {value !== undefined ? formatValue(value) : "-"}
        </span>
      </div>
    </div>
  );
}

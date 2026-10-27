import { NumberSlider } from "@/components/interaction/NumberSlider";

interface SliderWithValueProps {
  value?: number;
  min?: number;
  max?: number;
  step?: number;
  marks?: Record<number, string>;
  onChange?: (value: number) => void;
}

export function SliderWithValue(props: SliderWithValueProps) {
  return <NumberSlider {...props} />;
}

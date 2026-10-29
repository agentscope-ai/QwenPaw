export function providerColor(model: string): string {
  if (model.toLowerCase().startsWith("qwen")) return "#6d5ce7";
  if (model.toLowerCase().startsWith("glm")) return "#252525";
  return "#888888";
}

export default function Dot({
  model,
  harness,
  radius = 9,
}: {
  model: string;
  harness: string;
  radius?: number;
}) {
  const upper = `M ${-radius} 0 A ${radius} ${radius} 0 0 1 ${radius} 0`;
  const lower = `M ${-radius} 0 A ${radius} ${radius} 0 0 0 ${radius} 0`;
  const border =
    harness === "qwenpaw-goal"
      ? "#2563eb"
      : harness === "qwenpaw-code"
      ? "#111111"
      : undefined;
  return (
    <g pointerEvents="none">
      <path d={`${upper} Z`} fill={providerColor(model)} />
      <path d={`${lower} Z`} fill="#FF7F16" />
      {border && (
        <path d={lower} fill="none" stroke={border} strokeWidth={2.5} />
      )}
    </g>
  );
}

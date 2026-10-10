export const SOURCE_LABELS: Record<string, string> = {
  qwenpaw: "QwenPaw",
  clawhub: "ClawHub",
  modelscope: "ModelScope",
  aliyun: "Aliyun",
};

export function sourceLabel(source: string, label?: string | null): string {
  return label || SOURCE_LABELS[source] || source;
}

export const SOURCE_LABELS: Record<string, string> = {
  qwenpaw: "QwenPaw",
  clawhub: "ClawHub",
  modelscope: "ModelScope",
  aliyun: "Aliyun",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

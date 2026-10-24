/*
 * JSON 取值小工具 —— ArkTS 里 JSON.parse 的返回值是 Object，动态形状只能按
 * Record<string, Object> 逐字段取（平台/社区接口字段名多为 snake_case）。
 * 统一收口，避免各处重复写类型判定。
 */

export function objOf(value: Object): Record<string, Object> | null {
  if (value === undefined || value === null || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, Object>;
}

export function strOf(o: Record<string, Object>, key: string, fallback: string): string {
  const v: Object = o[key];
  return typeof v === 'string' ? v as string : fallback;
}

export function numOf(o: Record<string, Object>, key: string, fallback: number): number {
  const v: Object = o[key];
  return typeof v === 'number' ? v as number : fallback;
}

export function boolOf(o: Record<string, Object>, key: string, fallback: boolean): boolean {
  const v: Object = o[key];
  return typeof v === 'boolean' ? v as boolean : fallback;
}

export function strArrOf(o: Record<string, Object>, key: string): string[] {
  const v: Object = o[key];
  const out: string[] = [];
  if (Array.isArray(v)) {
    for (const item of v as Object[]) {
      if (typeof item === 'string') {
        out.push(item as string);
      }
    }
  }
  return out;
}

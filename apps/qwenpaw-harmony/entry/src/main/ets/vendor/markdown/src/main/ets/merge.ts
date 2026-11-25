// 深层合并工具函数（支持对象、数组、基本类型）
export default function deepMerge<T extends object>(...sources: (Partial<T> | undefined)[]): T {
  const result: Partial<T> = {};

  sources.forEach(source => {
    if (!source) {
      return;
    }

    Object.keys(source).forEach(key => {
      const keyTyped = key as keyof T;
      const currentValue = result[keyTyped];
      const sourceValue = source[keyTyped];

      // 处理嵌套对象（非数组、非基本类型）
      if (
        sourceValue !== null &&
          typeof sourceValue === 'object' &&
          !Array.isArray(sourceValue)
      ) {
        result[keyTyped] = deepMerge(
          (currentValue as object) || {},
          sourceValue as object
        ) as T[Extract<keyof T, string>];
      }
      // 处理数组（直接替换）
      else if (Array.isArray(sourceValue)) {
        result[keyTyped] = [...sourceValue] as T[Extract<keyof T, string>];
      }
      // 基本类型（直接覆盖）
      else {
        result[keyTyped] = sourceValue as T[Extract<keyof T, string>];
      }
    });
  });

  return result as T;
}
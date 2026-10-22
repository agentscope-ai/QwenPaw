/** Runtime validation of the JSON Schema subset emitted by our public models.
 * Cross-field/state invariants remain authoritative on the Host.
 */
import { contractSchemas } from "./contracts.generated";
import type { ContractMap } from "./contracts.generated";
export type * from "./contracts.generated";

type Schema = Record<string, unknown>;
const schemas = contractSchemas as unknown as Record<string, Schema>;
function valid(s: Schema, value: unknown, depth = 0): boolean {
  if (depth > 64) return false;
  if (s.$ref)
    return valid(
      schemas[String(s.$ref).split("/").pop()!] ?? { type: "never" },
      value,
      depth + 1,
    );
  if (Array.isArray(s.anyOf))
    return s.anyOf.some((x) => valid(x as Schema, value, depth + 1));
  if ("const" in s && value !== s.const) return false;
  if (Array.isArray(s.enum) && !s.enum.includes(value)) return false;
  switch (s.type) {
    case undefined:
      return true;
    case "null":
      return value === null;
    case "boolean":
      return typeof value === "boolean";
    case "string":
      return (
        typeof value === "string" &&
        [...value].length >= Number(s.minLength ?? 0) &&
        [...value].length <= Number(s.maxLength ?? Infinity) &&
        (!s.pattern || new RegExp(String(s.pattern)).test(value))
      );
    case "integer":
    case "number":
      return (
        typeof value === "number" &&
        Number.isFinite(value) &&
        (s.type !== "integer" || Number.isSafeInteger(value)) &&
        value >= Number(s.minimum ?? -Infinity) &&
        value <= Number(s.maximum ?? Infinity) &&
        value > Number(s.exclusiveMinimum ?? -Infinity) &&
        value < Number(s.exclusiveMaximum ?? Infinity)
      );
    case "array":
      return (
        Array.isArray(value) &&
        value.length >= Number(s.minItems ?? 0) &&
        value.length <= Number(s.maxItems ?? Infinity) &&
        value.every((v) => valid((s.items ?? {}) as Schema, v, depth + 1))
      );
    case "object": {
      if (!value || typeof value !== "object" || Array.isArray(value))
        return false;
      const data = value as Record<string, unknown>;
      const props = (s.properties ?? {}) as Record<string, Schema>;
      const required = (s.required ?? []) as string[];
      const keys = Object.keys(data);
      return (
        keys.length <= Number(s.maxProperties ?? Infinity) &&
        required.every((k) => Object.prototype.hasOwnProperty.call(data, k)) &&
        keys.every((k) => {
          if (
            s.propertyNames &&
            !valid(s.propertyNames as Schema, k, depth + 1)
          )
            return false;
          if (Object.prototype.hasOwnProperty.call(props, k))
            return valid(props[k], data[k], depth + 1);
          return (
            s.additionalProperties !== false &&
            (typeof s.additionalProperties !== "object" ||
              valid(s.additionalProperties as Schema, data[k], depth + 1))
          );
        })
      );
    }
    default:
      return false;
  }
}

export function assertContract<K extends keyof ContractMap>(
  name: K,
  value: unknown,
): ContractMap[K] {
  if (!valid(schemas[name], value)) throw new Error(`invalid_${name}`);
  return value as ContractMap[K];
}

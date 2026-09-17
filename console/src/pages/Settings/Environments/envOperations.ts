import type { EnvOperation } from "../../../api/types";
import type { Row } from "./components";

/** Convert UI drafts into explicit write-only operations. */
export function buildEnvOperations(rows: Row[]): EnvOperation[] {
  return rows.map((row) => {
    const key = row.key.trim();
    if (row.isNew || row.valueChanged) {
      return { key, action: "replace", value: row.value };
    }
    return { key, action: "keep" };
  });
}

import { runInNewContext } from "node:vm";

/** Create an actual Error whose constructor belongs to another realm. */
export function createForeignError(
  message: string,
  name: "Error" | "TypeError" = "TypeError",
): Error {
  return runInNewContext(`new ${name}(${JSON.stringify(message)})`) as Error;
}

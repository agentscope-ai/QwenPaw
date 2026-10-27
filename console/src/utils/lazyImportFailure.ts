// Keep diagnostic metadata independent of React and the page import graph.
export const importFailures = new WeakMap<
  object,
  { attempts: number; modulePath?: string }
>();

export function getLazyImportFailure(error: object) {
  return importFailures.get(error);
}

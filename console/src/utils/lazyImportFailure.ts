// Keep diagnostic metadata independent of React and the page import graph.
export const importFailures = new WeakMap<
  Error,
  { attempts: number; modulePath?: string }
>();

export function getLazyImportFailure(error: Error) {
  return importFailures.get(error);
}

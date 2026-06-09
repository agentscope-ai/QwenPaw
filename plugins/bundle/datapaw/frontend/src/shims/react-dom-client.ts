/**
 * `react-dom/client` shim — exposes `createRoot` / `hydrateRoot` from the
 * host ReactDOM. The plugin itself never calls these (the host owns the
 * root); the shim exists so the bundled console's `main.tsx`-style code
 * does not crash if it somehow ends up imported transitively.
 */

const RD: any = (window as any).QwenPaw?.host?.ReactDOM;
if (!RD) {
  throw new Error(
    "[datapaw-plugin] window.QwenPaw.host.ReactDOM missing — host console too old?",
  );
}

// react-dom/client first appeared in React 18; the host exposes the full
// ReactDOM object so `createRoot` lives directly on it.
export const createRoot = RD.createRoot;
export const hydrateRoot = RD.hydrateRoot;

export default { createRoot, hydrateRoot };

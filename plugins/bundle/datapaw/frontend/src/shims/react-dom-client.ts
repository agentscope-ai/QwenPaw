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

type CreateRootFn = typeof import("react-dom/client").createRoot;
type HydrateRootFn = typeof import("react-dom/client").hydrateRoot;

function legacyCreateRoot(container: Element | DocumentFragment) {
  return {
    render(children: unknown) {
      RD.render(children, container);
    },
    unmount() {
      RD.unmountComponentAtNode(container as Element);
    },
  };
}

// Host exposes `react-dom` default export; `createRoot` may live on
// `react-dom/client` instead of the legacy ReactDOM namespace.
export const createRoot: CreateRootFn =
  typeof RD.createRoot === "function"
    ? RD.createRoot.bind(RD)
    : (legacyCreateRoot as CreateRootFn);

export const hydrateRoot: HydrateRootFn =
  typeof RD.hydrateRoot === "function"
    ? RD.hydrateRoot.bind(RD)
    : (legacyCreateRoot as HydrateRootFn);

export default { createRoot, hydrateRoot };

/**
 * `react-dom` shim — re-exports the host's ReactDOM instance.
 *
 * Same rationale as `./react.ts`: avoid shipping a second copy of
 * react-dom in the plugin bundle.
 */

const RD: any = (window as any).QwenPaw?.host?.ReactDOM;
if (!RD) {
  throw new Error(
    "[datapaw-plugin] window.QwenPaw.host.ReactDOM missing — host console too old?",
  );
}

export default RD;

export const createPortal = RD.createPortal;
export const flushSync = RD.flushSync;
export const findDOMNode = RD.findDOMNode;
export const unmountComponentAtNode = RD.unmountComponentAtNode;
export const render = RD.render;
export const hydrate = RD.hydrate;
export const version = RD.version;
export const unstable_batchedUpdates = RD.unstable_batchedUpdates;

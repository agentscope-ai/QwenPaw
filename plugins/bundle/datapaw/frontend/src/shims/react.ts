/**
 * `react` shim — re-exports the host's React instance.
 *
 * The plugin bundle is loaded inside the running host console which already
 * has a singleton React on `window.QwenPaw.host.React`. Bundling our own
 * second copy would break hooks (React enforces "one React per tree"). So
 * `vite.config.ts` aliases `react` → this file, and every named export we
 * commonly use is forwarded to the host instance.
 *
 * If a future console version exposes a new hook (say, `useFormStatus`) and
 * the bundled console code references it, just add it to the list below.
 */

const R: any = (window as any).QwenPaw?.host?.React;
if (!R) {
  throw new Error(
    "[datapaw-plugin] window.QwenPaw.host.React missing — is the host console " +
      "≥ the plugin-loader version?",
  );
}

export default R;

// ---- Hooks ----------------------------------------------------------------

export const useState = R.useState;
export const useEffect = R.useEffect;
export const useMemo = R.useMemo;
export const useCallback = R.useCallback;
export const useRef = R.useRef;
export const useContext = R.useContext;
export const useReducer = R.useReducer;
export const useImperativeHandle = R.useImperativeHandle;
export const useLayoutEffect = R.useLayoutEffect;
export const useDebugValue = R.useDebugValue;
export const useTransition = R.useTransition;
export const useDeferredValue = R.useDeferredValue;
export const useId = R.useId;
export const useSyncExternalStore = R.useSyncExternalStore;
export const useInsertionEffect = R.useInsertionEffect;

// ---- Top-level API --------------------------------------------------------

export const createContext = R.createContext;
export const createElement = R.createElement;
export const cloneElement = R.cloneElement;
export const isValidElement = R.isValidElement;
export const createRef = R.createRef;
export const forwardRef = R.forwardRef;
export const memo = R.memo;
export const lazy = R.lazy;
export const startTransition = R.startTransition;

export const Children = R.Children;
export const Fragment = R.Fragment;
export const Suspense = R.Suspense;
export const StrictMode = R.StrictMode;
export const Profiler = R.Profiler;
export const Component = R.Component;
export const PureComponent = R.PureComponent;

export const version = R.version;
export const act = R.act;

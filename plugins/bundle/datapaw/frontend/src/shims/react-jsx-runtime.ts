/**
 * `react/jsx-runtime` and `react/jsx-dev-runtime` shim.
 *
 * Vite's React plugin compiles `<Foo />` to `jsx(Foo, props)` from
 * `react/jsx-runtime` (the "automatic" JSX runtime added in React 17).
 * Since we cannot ship our own React, we forward `jsx`/`jsxs`/`Fragment`
 * to the host's React.
 *
 * Modern React ships these helpers on its top-level export object as
 * `React.jsx` / `React.jsxs` / `React.jsxDEV`. We prefer those when
 * available; otherwise we emulate them with `createElement` (slightly
 * different key-handling but behaviourally compatible for app code).
 */

const R: any = (window as any).QwenPaw?.host?.React;
if (!R) {
  throw new Error(
    "[datapaw-plugin] window.QwenPaw.host.React missing — host console too old?",
  );
}

export const Fragment = R.Fragment;

function emulateJsx(type: any, props: any, key?: any) {
  const { children, ...rest } = props ?? {};
  const config: any = key !== undefined ? { ...rest, key } : rest;
  if (children === undefined) return R.createElement(type, config);
  if (Array.isArray(children)) return R.createElement(type, config, ...children);
  return R.createElement(type, config, children);
}

// Prefer the host's native fast path (correct ref/key semantics + dev warnings).
export const jsx = R.jsx ?? emulateJsx;
export const jsxs = R.jsxs ?? emulateJsx;
export const jsxDEV = R.jsxDEV ?? emulateJsx;

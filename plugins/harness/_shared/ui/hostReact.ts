import { getHost } from "@qwenpaw/plugin-sdk";

// Lucide's static icons use the same React instance as their host panel.
const React = getHost().host.React;
export const { createElement, forwardRef } = React;
export default React;

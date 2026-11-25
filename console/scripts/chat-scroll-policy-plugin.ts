import type { Plugin as OptimizerPlugin } from "esbuild";
import type { Plugin } from "vite";

const sdkPolicyPath =
  /[\\/]@agentscope-ai[\\/]chat[\\/]lib[\\/]AgentScopeRuntimeWebUI[\\/]core[\\/]Chat[\\/]MessageList[\\/]messageScrollPolicy\.js$/;

// The pinned SDK has no auto-scroll option. Keep its initial positioning,
// but let the host preserve the viewport for updates within an open chat.
const policy = `export function shouldScrollForMessageUpdate(
  previous, next, previousSessionId, nextSessionId,
) {
  return next.length > 0 && (
    previousSessionId !== nextSessionId || previous.length === 0
  );
}`;

export const chatScrollPolicyPlugin: Plugin = {
  name: "qwenpaw-chat-scroll-policy",
  enforce: "pre",
  load(id) {
    if (sdkPolicyPath.test(id)) return policy;
  },
};

// Vite's dependency pre-bundle does not run the regular load hook.
export const chatScrollPolicyOptimizer: OptimizerPlugin = {
  name: chatScrollPolicyPlugin.name,
  setup(build) {
    build.onLoad({ filter: sdkPolicyPath }, () => ({ contents: policy }));
  },
};

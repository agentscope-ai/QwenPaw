import { resolve } from "node:path";
import type { PluginBuild } from "esbuild";
import { describe, expect, it } from "vitest";
import {
  chatScrollPolicyOptimizer,
  chatScrollPolicyPlugin,
} from "./chat-scroll-policy-plugin";

async function loadPatchedSdkModule(path: string): Promise<string> {
  const load = chatScrollPolicyPlugin.load;
  if (typeof load !== "function") {
    throw new Error("The SDK scroll patch must use a Vite load hook.");
  }
  const result = await load.call({} as never, path, { ssr: false });
  if (typeof result !== "string") {
    throw new Error("The SDK scroll patch did not return module source.");
  }
  return result;
}

function loadOptimizedSdkModule(path: string): string {
  const setup = chatScrollPolicyOptimizer.setup;
  if (typeof setup !== "function") {
    throw new Error("The SDK scroll optimizer must register an onLoad hook.");
  }
  let handler: unknown;
  setup({
    onLoad: (_options, callback) => {
      handler = callback;
    },
  } as unknown as PluginBuild);
  if (typeof handler !== "function") {
    throw new Error("The SDK scroll optimizer did not register its hook.");
  }
  const result = handler({ path }) as { contents?: string };
  if (typeof result.contents !== "string") {
    throw new Error("The SDK scroll optimizer did not return module source.");
  }
  return result.contents;
}

describe("chat scroll SDK patch", () => {
  it("keeps a return-to-latest button for an older pagination window", async () => {
    const messageListPath = resolve(
      process.cwd(),
      "node_modules/@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Chat/MessageList/index.js",
    );
    const bubbleListPath = resolve(
      process.cwd(),
      "node_modules/@agentscope-ai/chat/lib/Bubble/BubbleList.js",
    );

    const messageList = await loadPatchedSdkModule(messageListPath);
    const bubbleList = await loadPatchedSdkModule(bubbleListPath);

    expect(messageList).toContain("hasMoreRecent: historyRange.start > 0");
    expect(messageList).toContain(
      "showScrollToLatest: _useSimulatedMessageP.hasMoreRecent",
    );
    expect(bubbleList).toContain("if (props.showScrollToLatest) return true;");
    expect(bubbleList).toContain("[isDesc, props.showScrollToLatest]");
    expect(bubbleList).toContain("props.onScrollToLatest();");
  });

  it("applies the same patch during dependency pre-bundling", () => {
    const bubbleListPath = resolve(
      process.cwd(),
      "node_modules/@agentscope-ai/chat/lib/Bubble/BubbleList.js",
    );
    const bubbleList = loadOptimizedSdkModule(bubbleListPath);

    expect(bubbleList).toContain("if (props.showScrollToLatest) return true;");
    expect(bubbleList).toContain("props.onScrollToLatest();");
  });
});

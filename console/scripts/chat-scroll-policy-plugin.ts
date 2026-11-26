import { readFileSync } from "node:fs";
import type { Plugin as OptimizerPlugin } from "esbuild";
import type { Plugin } from "vite";

const sdkPolicyPath =
  /[\\/]@agentscope-ai[\\/]chat[\\/]lib[\\/]AgentScopeRuntimeWebUI[\\/]core[\\/]Chat[\\/]MessageList[\\/]messageScrollPolicy\.js$/;
const sdkMessageListPath =
  /[\\/]@agentscope-ai[\\/]chat[\\/]lib[\\/]AgentScopeRuntimeWebUI[\\/]core[\\/]Chat[\\/]MessageList[\\/]index\.js$/;
const sdkBubbleListPath =
  /[\\/]@agentscope-ai[\\/]chat[\\/]lib[\\/]Bubble[\\/]BubbleList\.js$/;
const sdkScrollPaths = new RegExp(
  [sdkPolicyPath, sdkMessageListPath, sdkBubbleListPath]
    .map((pattern) => pattern.source)
    .join("|"),
);

// The pinned SDK has no auto-scroll option. Keep its initial positioning,
// but let the host preserve the viewport for updates within an open chat.
const policy = `export function shouldScrollForMessageUpdate(
  previous, next, previousSessionId, nextSessionId,
) {
  return next.length > 0 && (
    previousSessionId !== nextSessionId || previous.length === 0
  );
}`;

function replaceSdkCode(source: string, needle: string, replacement: string) {
  if (!source.includes(needle)) {
    throw new Error("Recheck the QwenPaw chat scroll patch against the SDK.");
  }
  return source.replace(needle, replacement);
}

function loadSdkScrollPatch(id: string) {
  if (sdkPolicyPath.test(id)) return policy;
  if (sdkMessageListPath.test(id)) {
    const source = readFileSync(id, "utf8");
    // An anchor-directory jump can move both ends of the pagination window.
    // Returning to latest must restore the newest page, not just scroll.
    return replaceSdkCode(
      replaceSdkCode(
        source,
        "ensureMessageVisible: ensureMessageVisible\n  };",
        `ensureMessageVisible: ensureMessageVisible,
    hasMoreRecent: historyRange.start > 0,
    showLatest: function () {
      ensureMessageSequenceRef.current += 1;
      if (historyRangeRef.current.start > 0) setHistoryRange(INITIAL_HISTORY_RANGE);
    }
  };`,
      ),
      "items: visibleMessages\n    }, currentSessionId)",
      "items: visibleMessages,\n      showScrollToLatest: _useSimulatedMessageP.hasMoreRecent,\n      onScrollToLatest: _useSimulatedMessageP.showLatest\n    }, currentSessionId)",
    );
  }
  if (sdkBubbleListPath.test(id)) {
    const source = readFileSync(id, "utf8");
    return replaceSdkCode(
      replaceSdkCode(
        replaceSdkCode(
          source,
          "    if (!scrollEl) return false;\n    var hasOverflow =",
          "    if (!scrollEl) return false;\n    if (props.showScrollToLatest) return true;\n    var hasOverflow =",
        ),
        "  }, [isDesc]);\n  var scrollToBottom",
        "  }, [isDesc, props.showScrollToLatest]);\n  var scrollToBottom",
      ),
      "return scrollToBottom('auto');\n        }",
      `if (props.onScrollToLatest) {
            scrollRef.current?.dispatchEvent(new Event('qwenpaw:chat-scroll-to-latest'));
            props.onScrollToLatest();
          }
          return scrollToBottom('auto');
        }`,
    );
  }
}

export const chatScrollPolicyPlugin: Plugin = {
  // The optimizer uses the plugin name in its dependency cache key.
  name: "qwenpaw-chat-scroll-policy-v2",
  enforce: "pre",
  load: loadSdkScrollPatch,
};

// Vite's dependency pre-bundle does not run the regular load hook.
export const chatScrollPolicyOptimizer: OptimizerPlugin = {
  name: chatScrollPolicyPlugin.name,
  setup(build) {
    build.onLoad({ filter: sdkScrollPaths }, ({ path }) => ({
      contents: loadSdkScrollPatch(path),
    }));
  },
};

import "./runtime";
import { OpenUIBlock } from "./OpenUIBlock";
import { getHost, PLUGIN_ID } from "./host";

const api = getHost();
if (!api?.chat?.codeBlock || !api.chat.submit || !api.host.openExternalLink) {
  throw new Error(
    "QwenPaw OpenUI requires QwenPaw with chat.codeBlock, chat.submit and host.openExternalLink. Please update QwenPaw.",
  );
}

api.chat.disposeAll(PLUGIN_ID);
const renderer = api.chat.codeBlock(PLUGIN_ID, "openui-lang", OpenUIBlock);
try {
  api.chat.requestPayload.add(PLUGIN_ID, ({ payload }) => {
    const context =
      payload.request_context && typeof payload.request_context === "object"
        ? (payload.request_context as Record<string, unknown>)
        : {};
    const capabilities =
      context.ui_capabilities && typeof context.ui_capabilities === "object"
        ? (context.ui_capabilities as Record<string, unknown>)
        : {};
    return {
      ...payload,
      request_context: {
        ...context,
        ui_capabilities: { ...capabilities, openui: "v1" },
      },
    };
  });
} catch (error) {
  renderer.dispose();
  throw error;
}

import { chatExtensions } from "../../plugins/registry/chatExtensions";
import { ChatList } from "../../plugins/registry/slotKeys";
import { attachClientMessageId } from "../../utils/clientMessageId";

/** Both foreground SDK sends and host background sends use this pipeline. */
export function applyChatPayloadTransforms(
  payload: Record<string, unknown>,
  agentId: string,
  clientMessageId?: string,
  transforms = chatExtensions.getListSnapshot()[
    ChatList.requestPayloadTransforms
  ],
  controls?: Record<string, unknown>,
): Record<string, unknown> {
  let requestBody = payload;
  for (const entry of transforms
    .slice()
    .sort((a, b) => (a.item.order ?? 100) - (b.item.order ?? 100))) {
    const next = entry.item.transform({
      payload: requestBody,
      sessionId: String(requestBody.session_id || ""),
      selectedAgent: agentId,
    });
    if (next && typeof next === "object") requestBody = next;
  }
  // Keep the receipt identity even when an extension replaces input records.
  if (clientMessageId && Array.isArray(requestBody.input)) {
    const input = [...requestBody.input] as Array<Record<string, unknown>>;
    for (let i = input.length - 1; i >= 0; i--) {
      if (input[i]?.role !== "user") continue;
      input[i] = attachClientMessageId(input[i], clientMessageId);
      requestBody = { ...requestBody, input };
      break;
    }
  }
  // Host approval/backend controls are frozen when the user submits. A
  // background handoff or a plugin replacement must not drop that policy.
  if (controls && (controls.approval_level || controls.backend_controls)) {
    const existing = requestBody.request_context;
    requestBody = {
      ...requestBody,
      request_context: {
        ...(existing && typeof existing === "object" ? existing : {}),
        ...(controls.approval_level
          ? { approval_level: controls.approval_level }
          : {}),
        ...(controls.backend_controls
          ? { backend_controls: controls.backend_controls }
          : {}),
      },
    };
  }
  return requestBody;
}

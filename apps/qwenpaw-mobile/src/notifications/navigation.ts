import type { MobileNotificationData } from "@qwenpaw/api-contract";
import { router } from "expo-router";

import { useAppStore } from "../store/app";
import { connectionKey } from "../storage/connection";
import { workspaceKey } from "./storage";
import { notificationDestination } from "./navigationModel";

export async function openNotificationTarget(
  data: MobileNotificationData,
): Promise<void> {
  const state = useAppStore.getState();
  const matches = await Promise.all(
    state.connections.map(async (connection) => ({
      connection,
      key: await workspaceKey(connection),
    })),
  );
  const match = matches.find((item) => item.key === data.workspace_key);
  if (!match) return;
  if (
    !state.connection ||
    connectionKey(state.connection) !== connectionKey(match.connection)
  ) {
    await useAppStore
      .getState()
      .switchConnection(connectionKey(match.connection));
  }
  const active = useAppStore.getState().connection;
  if (active && active.agentId !== data.agent_id) {
    await useAppStore.getState().selectAgent(data.agent_id);
  }
  const destination = notificationDestination(data);
  if (destination.kind === "approval") {
    router.replace({ pathname: "/(tabs)/chats", params: { approval: "1" } });
    return;
  }
  if (destination.kind === "chat") {
    router.replace({
      pathname: "/chat/[id]",
      params: { id: destination.chatId },
    });
    return;
  }
  router.replace("/(tabs)/workbench");
}

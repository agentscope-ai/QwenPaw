import type { NotificationPreferences } from "@qwenpaw/api-contract";
import Constants from "expo-constants";
import * as Device from "expo-device";
import { Platform } from "react-native";

import { QwenPawClient } from "../api/client";
import type { Connection } from "../api/types";
import {
  getInstallationId,
  loadNotificationPreferences,
  saveNotificationPreferences,
  workspaceKey,
} from "./storage";

export type NotificationSetupState =
  | "disabled"
  | "ready"
  | "denied"
  | "device_required"
  | "project_required";

export interface NotificationSetupResult {
  state: NotificationSetupState;
  preferences: NotificationPreferences;
}

type NotificationsModule = typeof import("expo-notifications");

async function loadNotifications(): Promise<NotificationsModule> {
  return import("expo-notifications");
}

export async function configureNotificationChannel(): Promise<void> {
  if (Platform.OS !== "android") return;
  const Notifications = await loadNotifications();
  await Notifications.setNotificationChannelAsync("qwenpaw-tasks", {
    name: "QwenPaw 任务",
    description: "任务完成、等待输入、审批和失败提醒",
    importance: Notifications.AndroidImportance.HIGH,
    vibrationPattern: [0, 180, 120, 180],
    lightColor: "#C84A00",
    lockscreenVisibility: Notifications.AndroidNotificationVisibility.PRIVATE,
  });
}

function easProjectId(): string | null {
  const direct = Constants.easConfig?.projectId;
  if (direct) return direct;
  const extra = Constants.expoConfig?.extra;
  if (!extra || typeof extra !== "object") return null;
  const eas = (extra as Record<string, unknown>).eas;
  if (!eas || typeof eas !== "object") return null;
  const value = (eas as Record<string, unknown>).projectId;
  return typeof value === "string" && value ? value : null;
}

async function permissionGranted(requestPermission: boolean): Promise<boolean> {
  const Notifications = await loadNotifications();
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) return true;
  if (!requestPermission || !current.canAskAgain) return false;
  const requested = await Notifications.requestPermissionsAsync({
    ios: {
      allowAlert: true,
      allowBadge: true,
      allowSound: true,
    },
  });
  return requested.granted;
}

export async function syncPushSubscription(
  connection: Connection,
  preferences?: NotificationPreferences,
  requestPermission = false,
): Promise<NotificationSetupResult> {
  const resolved =
    preferences ?? (await loadNotificationPreferences(connection));
  if (!resolved.enabled) return { state: "disabled", preferences: resolved };
  if (!Device.isDevice) {
    return { state: "device_required", preferences: resolved };
  }
  await configureNotificationChannel();
  if (!(await permissionGranted(requestPermission))) {
    return { state: "denied", preferences: resolved };
  }
  const projectId = easProjectId();
  if (!projectId) {
    return { state: "project_required", preferences: resolved };
  }
  const Notifications = await loadNotifications();
  const [installationId, hashedWorkspace, token] = await Promise.all([
    getInstallationId(),
    workspaceKey(connection),
    Notifications.getExpoPushTokenAsync({ projectId }),
  ]);
  const client = new QwenPawClient(connection);
  const response = await client.upsertMobilePushSubscription({
    installation_id: installationId,
    workspace_key: hashedWorkspace,
    agent_id: connection.agentId || "default",
    platform: Platform.OS === "ios" ? "ios" : "android",
    expo_push_token: token.data,
    preferences: resolved,
  });
  await saveNotificationPreferences(connection, response.preferences);
  return { state: "ready", preferences: response.preferences };
}

export async function disablePushSubscription(
  connection: Connection,
  preferences: NotificationPreferences,
  signal?: AbortSignal,
): Promise<NotificationPreferences> {
  const disabled = { ...preferences, enabled: false };
  await saveNotificationPreferences(connection, disabled);
  const [installationId, hashedWorkspace] = await Promise.all([
    getInstallationId(),
    workspaceKey(connection),
  ]);
  await new QwenPawClient(connection, signal)
    .deleteMobilePushSubscription(installationId, hashedWorkspace)
    .catch(() => undefined);
  return disabled;
}

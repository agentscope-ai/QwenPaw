import {
  parseMobileNotificationData,
  type MobileNotificationData,
} from "@qwenpaw/api-contract";
import * as Device from "expo-device";
import type * as NotificationsType from "expo-notifications";

type Consumer = (data: MobileNotificationData) => void | Promise<void>;

let consumer: Consumer | null = null;
let queued: MobileNotificationData | null = null;
let lastIdentifier: string | null = null;
let responseSubscription: NotificationsType.EventSubscription | null = null;

function receive(response: NotificationsType.NotificationResponse): void {
  const identifier = response.notification.request.identifier;
  if (identifier === lastIdentifier) return;
  const data = parseMobileNotificationData(
    response.notification.request.content.data,
  );
  if (!data) return;
  lastIdentifier = identifier;
  if (consumer) void consumer(data);
  else queued = data;
}

async function loadNotifications(): Promise<typeof NotificationsType> {
  return import("expo-notifications");
}

async function ensureNotifications(): Promise<typeof NotificationsType | null> {
  if (!Device.isDevice) return null;
  const Notifications = await loadNotifications();
  if (!responseSubscription) {
    Notifications.setNotificationHandler({
      handleNotification: async () => ({
        shouldPlaySound: true,
        shouldSetBadge: false,
        shouldShowBanner: true,
        shouldShowList: true,
      }),
    });
    responseSubscription =
      Notifications.addNotificationResponseReceivedListener(receive);
  }
  return Notifications;
}

export async function startNotificationNavigation(
  nextConsumer: Consumer,
): Promise<() => void> {
  consumer = nextConsumer;
  const Notifications = await ensureNotifications();
  const initial = await Notifications?.getLastNotificationResponseAsync();
  if (initial) receive(initial);
  if (queued) {
    const pending = queued;
    queued = null;
    await nextConsumer(pending);
  }
  return () => {
    if (consumer === nextConsumer) consumer = null;
  };
}

import { MobileAlert } from "@/components/MobileAlert";
import { Mail, ShieldCheck, UserCheck, UserPlus, UserX } from "lucide-react-native";
import { useCallback, useEffect, useMemo, useState } from "react";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { DynamicConfigSheet } from "./DynamicConfigSheet";

interface UserInfo {
  remark?: string;
  username?: string;
}

interface PendingEntry {
  user_id: string;
  channel: string;
  first_message?: string;
  remark?: string;
  username?: string;
}

interface AclData {
  whitelist: Record<string, UserInfo>;
  blacklist: Record<string, UserInfo>;
  pending: PendingEntry[];
}

interface MailUserInfo {
  remark?: string;
  display_name?: string;
}

interface MailAclData {
  whitelist: Record<string, MailUserInfo>;
  blacklist: Record<string, MailUserInfo>;
  pending: {
    sender_address: string;
    agent_id: string;
    display_name?: string;
    subject?: string;
    remark?: string;
  }[];
}

export function ChannelAccessSettings({ connection }: { connection: Connection }) {
  const [acl, setAcl] = useState<Record<string, AclData>>({});
  const [mailAcl, setMailAcl] = useState<Record<string, MailAclData>>({});
  const [supported, setSupported] = useState(false);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const client = new QwenPawClient(connection);
    const [channelResult, mailResult] = await Promise.allSettled([
      client.inspectModule("/access-control"),
      client.inspectModule("/mail-access-control"),
    ]);
    if (channelResult.status === "fulfilled" && isRecord(channelResult.value)) {
      setAcl(channelResult.value as Record<string, AclData>);
      setSupported(true);
    }
    if (mailResult.status === "fulfilled" && isRecord(mailResult.value)) {
      setMailAcl(mailResult.value as Record<string, MailAclData>);
      setSupported(true);
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const pending = useMemo(
    () => Object.values(acl).flatMap((item) => item.pending ?? []),
    [acl],
  );
  const mailPending = useMemo(
    () => Object.values(mailAcl).flatMap((item) => item.pending ?? []),
    [mailAcl],
  );
  const channels = Object.keys(acl);

  const run = async (action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    try {
      await action();
      await load();
    } catch (reason) {
      MobileAlert.alert("访问控制操作失败", errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  if (!supported) return null;

  return (
    <>
      <IosGroup title="访问控制">
        <IosRow
          icon={UserPlus}
          label="添加访问规则"
          onPress={() => setAdding(true)}
          subtitle="手动加入白名单或黑名单"
        />
        <IosRow
          icon={ShieldCheck}
          iconTone="ink"
          label="待处理请求"
          subtitle="消息渠道与邮件接入申请"
          trailing={String(pending.length + mailPending.length)}
        />
      </IosGroup>

      {pending.length ? (
        <IosGroup title={`渠道待审批 · ${pending.length}`}>
          {pending.map((entry) => (
            <IosRow
              icon={UserCheck}
              key={`${entry.channel}:${entry.user_id}`}
              label={entry.remark || entry.username || entry.user_id}
              onPress={() => openPending(entry)}
              subtitle={`${entry.channel}${entry.first_message ? ` · ${entry.first_message}` : ""}`}
              trailing="处理"
            />
          ))}
        </IosGroup>
      ) : null}

      {mailPending.length ? (
        <IosGroup title={`邮件待审批 · ${mailPending.length}`}>
          {mailPending.map((entry) => (
            <IosRow
              icon={Mail}
              iconTone="ink"
              key={`${entry.agent_id}:${entry.sender_address}`}
              label={entry.display_name || entry.sender_address}
              onPress={() => openMailPending(entry)}
              subtitle={`${entry.agent_id}${entry.subject ? ` · ${entry.subject}` : ""}`}
              trailing="处理"
            />
          ))}
        </IosGroup>
      ) : null}

      {Object.entries(acl).map(([channel, data]) => {
        const allowed = Object.entries(data.whitelist ?? {});
        const denied = Object.entries(data.blacklist ?? {});
        if (!allowed.length && !denied.length) return null;
        return (
          <IosGroup key={channel} title={`${channel} 访问名单`}>
            {allowed.map(([userId, info]) => (
              <IosRow
                icon={UserCheck}
                key={`allow:${userId}`}
                label={info.remark || info.username || userId}
                onPress={() => openExisting(channel, userId, "whitelist")}
                subtitle={userId}
                trailing="允许"
              />
            ))}
            {denied.map(([userId, info]) => (
              <IosRow
                icon={UserX}
                iconTone="ink"
                key={`deny:${userId}`}
                label={info.remark || info.username || userId}
                onPress={() => openExisting(channel, userId, "blacklist")}
                subtitle={userId}
                trailing="拒绝"
              />
            ))}
          </IosGroup>
        );
      })}

      {adding ? (
        <DynamicConfigSheet
          fields={[
            {
              name: "channel",
              label: "渠道",
              type: "select",
              required: true,
              options: channels.length ? channels : ["console"],
            },
            { name: "user_id", label: "用户 ID", type: "text", required: true },
            { name: "remark", label: "备注", type: "text" },
            {
              name: "effect",
              label: "规则",
              type: "select",
              required: true,
              options: ["允许", "拒绝"],
              default: "允许",
            },
          ]}
          onClose={() => setAdding(false)}
          onSave={async (values) => {
            const list = values.effect === "拒绝" ? "blacklist" : "whitelist";
            await new QwenPawClient(connection).mutateModule(
              `/access-control/${list}/add`,
              "POST",
              {
                entries: [{
                  channel: String(values.channel),
                  user_id: String(values.user_id).trim(),
                  remark: String(values.remark || "").trim(),
                }],
              },
            );
            await load();
          }}
          title="添加访问规则"
          values={{ channel: channels[0] ?? "console", effect: "允许" }}
        />
      ) : null}
    </>
  );

  function openPending(entry: PendingEntry) {
    const body = { entries: [{ channel: entry.channel, user_id: entry.user_id }] };
    MobileAlert.alert(entry.remark || entry.username || entry.user_id, entry.first_message, [
      { text: "取消", style: "cancel" },
      {
        text: "忽略",
        onPress: () => void run(() => new QwenPawClient(connection).mutateModule(
          "/access-control/pending/dismiss", "POST", body,
        )),
      },
      {
        text: "拒绝",
        style: "destructive",
        onPress: () => void run(() => new QwenPawClient(connection).mutateModule(
          "/access-control/pending/deny", "POST", body,
        )),
      },
      {
        text: "允许",
        onPress: () => void run(() => new QwenPawClient(connection).mutateModule(
          "/access-control/pending/approve", "POST", body,
        )),
      },
    ]);
  }

  function openMailPending(entry: MailAclData["pending"][number]) {
    const body = {
      entries: [{ agent_id: entry.agent_id, address: entry.sender_address }],
    };
    MobileAlert.alert(entry.display_name || entry.sender_address, entry.subject, [
      { text: "取消", style: "cancel" },
      {
        text: "忽略",
        onPress: () => void run(() => new QwenPawClient(connection).mutateModule(
          "/mail-access-control/pending/dismiss", "POST", body,
        )),
      },
      {
        text: "拒绝",
        style: "destructive",
        onPress: () => void run(() => new QwenPawClient(connection).mutateModule(
          "/mail-access-control/pending/deny", "POST", body,
        )),
      },
      {
        text: "允许",
        onPress: () => void run(() => new QwenPawClient(connection).mutateModule(
          "/mail-access-control/pending/approve", "POST", body,
        )),
      },
    ]);
  }

  function openExisting(
    channel: string,
    userId: string,
    list: "whitelist" | "blacklist",
  ) {
    MobileAlert.alert("管理访问规则", `${channel} · ${userId}`, [
      { text: "取消", style: "cancel" },
      {
        text: "移除规则",
        style: "destructive",
        onPress: () => void run(() => new QwenPawClient(connection).mutateModule(
          `/access-control/${list}/remove`,
          "POST",
          { entries: [{ channel, user_id: userId }] },
        )),
      },
    ]);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}

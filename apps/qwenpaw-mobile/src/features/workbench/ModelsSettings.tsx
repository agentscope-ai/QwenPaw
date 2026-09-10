import { MobileAlert } from "@/components/MobileAlert";
import { Bot, Check, Cpu, Plus, Settings2 } from "lucide-react-native";
import { useCallback, useEffect, useMemo, useState } from "react";

import { QwenPawClient } from "../../api/client";
import type { ActiveModelInfo, Connection, ProviderInfo } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { selectableProviders } from "../chat/sessionControlsModel";
import type { SelectableProvider } from "../chat/sessionControlsModel";
import { DynamicConfigSheet } from "./DynamicConfigSheet";
import { LocalModelSettings } from "./LocalModelSettings";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

export function ModelsSettings({ connection }: { connection: Connection }) {
  const [catalog, setCatalog] = useState<ProviderInfo[] | null>(null);
  const [active, setActive] = useState<ActiveModelInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [editingProvider, setEditingProvider] = useState<ProviderInfo | "new" | null>(null);
  const [addingModel, setAddingModel] = useState<ProviderInfo | null>(null);
  const providers = useMemo(
    () => catalog ? selectableProviders(catalog) : null,
    [catalog],
  );

  const load = useCallback(async () => {
    try {
      const client = new QwenPawClient(connection);
      const [catalog, selected] = await Promise.all([
        client.listProviders(),
        client.getActiveModel(connection.agentId),
      ]);
      setError(null);
      setCatalog(catalog);
      setActive(selected);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const choose = useCallback((provider: SelectableProvider, modelId: string) => {
    const model = provider.models.find((item) => item.id === modelId);
    if (!model || saving) return;
    MobileAlert.alert(
      "更改当前 Agent 模型？",
      `之后的新请求将使用 ${provider.name} / ${model.name}。`,
      [
        { text: "取消", style: "cancel" },
        {
          text: "使用此模型",
          onPress: () => {
            setSaving(`${provider.id}:${model.id}`);
            void new QwenPawClient(connection).setAgentActiveModel(
              connection.agentId,
              { provider_id: provider.id, model: model.id },
            ).then(setActive).catch((reason) => {
              MobileAlert.alert("模型切换失败", errorMessage(reason));
            }).finally(() => setSaving(null));
          },
        },
      ],
    );
  }, [connection, saving]);

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!providers || !active) return <ModuleLoading />;
  return (
    <>
      <IosGroup title="当前 Agent">
        <IosRow
          icon={Bot}
          label={active.active_llm?.model ?? "尚未选择模型"}
          subtitle={active.active_llm?.provider_id ?? connection.agentId}
          trailing={active.active_llm ? "使用中" : "未设置"}
        />
      </IosGroup>
      <IosGroup title="Provider 管理">
        <IosRow
          icon={Plus}
          label="添加自定义 Provider"
          onPress={() => setEditingProvider("new")}
          subtitle="OpenAI-compatible 或自定义网关"
        />
        {(catalog ?? []).map((provider) => (
          <IosRow
            icon={Settings2}
            iconTone="ink"
            key={provider.id}
            label={provider.name}
            onPress={() => openProviderActions(provider)}
            subtitle={provider.base_url || (provider.is_local ? "本地服务" : "未配置 Base URL")}
            trailing={provider.api_key || provider.require_api_key === false ? "已配置" : "待配置"}
          />
        ))}
      </IosGroup>
      <LocalModelSettings connection={connection} onChanged={load} />
      {!providers.length ? (
        <ModuleEmpty
          icon={Cpu}
          title="没有已配置模型"
          subtitle="配置 Provider 凭据，或在本地模型中启动一个可用模型。"
        />
      ) : null}
      {providers.map((provider) => (
        <IosGroup key={provider.id} title={provider.name}>
          {provider.models.map((model) => {
            const selected = active.active_llm?.provider_id === provider.id &&
              active.active_llm.model === model.id;
            return (
              <IosRow
                icon={selected ? Check : Cpu}
                iconTone={selected ? "orange" : "ink"}
                key={`${provider.id}:${model.id}`}
                label={model.name}
                onPress={selected ? undefined : () => choose(provider, model.id)}
                subtitle={model.supports_multimodal ? "支持多模态" : undefined}
                trailing={selected ? "当前" : undefined}
              />
            );
          })}
        </IosGroup>
      ))}
      <ModuleFooter>这里只显示当前 QwenPaw 真正可调用的 Provider 与模型。</ModuleFooter>
      {editingProvider ? (
        <DynamicConfigSheet
          fields={editingProvider === "new" ? [
            { name: "id", label: "Provider ID", type: "text", required: true },
            { name: "name", label: "显示名称", type: "text", required: true },
            { name: "default_base_url", label: "Base URL", type: "text" },
            { name: "api_key_prefix", label: "API Key 前缀", type: "text" },
          ] : [
            { name: "name", label: "显示名称", type: "text", required: true },
            { name: "base_url", label: "Base URL", type: "text" },
            { name: "api_key", label: "API Key", type: "password", help: "留空保持已有密钥。" },
            { name: "auth_mode", label: "认证方式", type: "select", options: ["api_key", "auth_token"] },
          ]}
          onClose={() => setEditingProvider(null)}
          onSave={async (values) => {
            const client = new QwenPawClient(connection);
            if (editingProvider === "new") {
              await client.mutateModule("/models/custom-providers", "POST", values);
            } else {
              await client.mutateModule(
                `/models/${encodeURIComponent(editingProvider.id)}/config`,
                "PUT",
                {
                  name: values.name,
                  base_url: values.base_url,
                  auth_mode: values.auth_mode,
                  ...(String(values.api_key || "") ? { api_key: values.api_key } : {}),
                },
              );
            }
            await load();
          }}
          title={editingProvider === "new" ? "添加 Provider" : `配置 ${editingProvider.name}`}
          values={editingProvider === "new" ? {} : {
            name: editingProvider.name,
            base_url: editingProvider.base_url,
            auth_mode: "api_key",
          }}
        />
      ) : null}
      {addingModel ? (
        <DynamicConfigSheet
          fields={[
            { name: "id", label: "Model ID", type: "text", required: true },
            { name: "name", label: "显示名称", type: "text", required: true },
            { name: "is_free", label: "免费模型", type: "switch" },
            { name: "supports_multimodal", label: "支持多模态", type: "switch" },
          ]}
          onClose={() => setAddingModel(null)}
          onSave={async (values) => {
            await new QwenPawClient(connection).mutateModule(
              `/models/${encodeURIComponent(addingModel.id)}/models`,
              "POST",
              values,
            );
            await load();
          }}
          title={`为 ${addingModel.name} 添加模型`}
          values={{}}
        />
      ) : null}
    </>
  );

  function openProviderActions(provider: ProviderInfo) {
    const client = new QwenPawClient(connection);
    MobileAlert.alert(provider.name, "Provider 与模型管理", [
      { text: "取消", style: "cancel" },
      { text: "配置凭据", onPress: () => setEditingProvider(provider) },
      { text: "添加模型", onPress: () => setAddingModel(provider) },
      ...(provider.supports_oauth ? [{
        text: provider.oauth_connected ? "OAuth 已连接" : "连接 OAuth",
        onPress: () => void client.mutateModule(
          `/providers/${encodeURIComponent(provider.id)}/oauth/start`,
          "POST",
        ).then(() => MobileAlert.alert("OAuth 已启动", "请按服务端返回的授权流程完成登录。"))
          .catch((reason) => MobileAlert.alert("OAuth 启动失败", errorMessage(reason))),
      }] : []),
      {
        text: "测试连接",
        onPress: () => void client.mutateModule<{ success?: boolean; message?: string }>(
          `/models/${encodeURIComponent(provider.id)}/test`,
          "POST",
        ).then((value) => MobileAlert.alert(value.success ? "连接正常" : "连接失败", value.message))
          .catch((reason) => MobileAlert.alert("连接失败", errorMessage(reason))),
      },
      ...(provider.is_custom ? [{
        text: "删除 Provider",
        style: "destructive" as const,
        onPress: () => void client.mutateModule(
          `/models/custom-providers/${encodeURIComponent(provider.id)}`,
          "DELETE",
        ).then(load).catch((reason) => MobileAlert.alert("删除失败", errorMessage(reason))),
      }] : []),
      ...(!provider.is_local ? [{
        text: "发现模型",
        onPress: () => void client.mutateModule(
          `/models/${encodeURIComponent(provider.id)}/discover?save=true`,
          "POST",
        ).then(load).catch((reason) => MobileAlert.alert("发现失败", errorMessage(reason))),
      }] : []),
    ]);
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "模型设置失败";
}

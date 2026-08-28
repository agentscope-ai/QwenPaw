import { Check } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";
import type { WorkbenchModule } from "./modules";
import { moduleSnapshotItems } from "./summary";
import type { ModuleSnapshotItem } from "./summary";

export function SnapshotSettings({
  connection,
  module,
}: {
  connection: Connection;
  module: WorkbenchModule;
}) {
  const [items, setItems] = useState<ModuleSnapshotItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!module.endpoint) return;
    try {
      const endpoint = module.endpoint.replace("{agentId}", connection.agentId);
      const payload = await new QwenPawClient(connection).inspectModule(endpoint);
      setError(null);
      setItems(moduleSnapshotItems(payload));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取失败");
    }
  }, [connection, module.endpoint]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!items) return <ModuleLoading />;
  if (!items.length) {
    return (
      <ModuleEmpty
        icon={module.icon}
        title="暂无数据"
        subtitle="当前 QwenPaw 已成功响应，但这里还没有配置。"
      />
    );
  }

  return (
    <>
      <IosGroup title={`当前配置 · ${items.length}`}>
        {items.map((item) => (
          <IosRow
            icon={module.icon}
            iconTone={module.iconTone}
            key={item.id}
            label={item.title}
            subtitle={item.subtitle}
          />
        ))}
      </IosGroup>
      <IosGroup title="连接状态">
        <IosRow icon={Check} label="已从当前 QwenPaw 同步" trailing={connection.agentId} />
      </IosGroup>
      <ModuleFooter>页面数据来自当前 QwenPaw，不使用预览或示例内容。</ModuleFooter>
    </>
  );
}

import { MobileAlert } from "@/components/MobileAlert";
import { Layers, Smartphone } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

type OffloadAction = "keep_foreground" | "offload";

export function OffloadSettings({ connection }: { connection: Connection }) {
  const [action, setAction] = useState<OffloadAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const value = await new QwenPawClient(connection)
        .inspectModule("/settings/offload-policy") as { default_action?: string };
      setError(null);
      setAction(value.default_action === "offload" ? "offload" : "keep_foreground");
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const save = async (default_action: OffloadAction) => {
    try {
      const value = await new QwenPawClient(connection).mutateModule<{
        default_action: OffloadAction;
      }>("/settings/offload-policy", "PUT", { default_action });
      setAction(value.default_action);
    } catch (reason) {
      MobileAlert.alert("保存失败", errorMessage(reason));
    }
  };

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!action) return <ModuleLoading />;

  return (
    <>
      <IosGroup title="长任务默认行为">
        <IosRow
          icon={Smartphone}
          label="保持在前台"
          onPress={() => void save("keep_foreground")}
          subtitle="等待工具完成后继续当前回复"
          trailing={action === "keep_foreground" ? "已选择" : ""}
        />
        <IosRow
          icon={Layers}
          iconTone="ink"
          label="转入后台"
          onPress={() => void save("offload")}
          subtitle="到达时限后转为后台任务"
          trailing={action === "offload" ? "已选择" : ""}
        />
      </IosGroup>
      <ModuleFooter>只控制默认策略；会话中的单次工具任务仍可单独调整。</ModuleFooter>
    </>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}

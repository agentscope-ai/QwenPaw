import { useFocusEffect } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";

import { QwenPawClient } from "../../api/client";
import type {
  ActiveModelInfo,
  ApprovalLevel,
  ChatSpec,
  Connection,
  LoopModeInfo,
  LoopSessionState,
  ModelSlotOverride,
  ProviderInfo,
} from "../../api/types";
import {
  loadSessionControls,
  normalizeApprovalLevel,
  saveSessionApprovalLevel,
  saveSessionModelOverride,
} from "../../storage/sessionControls";
import {
  DEFAULT_LOOP_MODE,
  normalizeLoopModes,
  selectableProviders,
} from "./sessionControlsModel";

interface MobileLoopStatus {
  state: LoopSessionState;
  mode: LoopModeInfo | null;
}

export function useSessionControls(
  connection: Connection | null,
  chat: ChatSpec | undefined,
) {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModel, setActiveModel] = useState<ActiveModelInfo | null>(null);
  const [runningApproval, setRunningApproval] = useState<ApprovalLevel>("AUTO");
  const [sessionApproval, setSessionApproval] = useState<ApprovalLevel | null>(null);
  const [sessionModelOverride, setSessionModelOverride] =
    useState<ModelSlotOverride | null>(null);
  const [loopModes, setLoopModes] = useState<LoopModeInfo[]>([DEFAULT_LOOP_MODE]);
  const [selectedLoopId, setSelectedLoopId] = useState(DEFAULT_LOOP_MODE.id);
  const [loopStatus, setLoopStatus] = useState<MobileLoopStatus>({
    state: "idle",
    mode: null,
  });
  const [loading, setLoading] = useState(true);
  const [savingModel, setSavingModel] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);
  const loadRevision = useRef(0);

  const load = useCallback(async () => {
    const revision = ++loadRevision.current;
    setProviders([]);
    setActiveModel(null);
    setRunningApproval("AUTO");
    setSessionApproval(null);
    setSessionModelOverride(null);
    setLoopModes([DEFAULT_LOOP_MODE]);
    setSelectedLoopId(DEFAULT_LOOP_MODE.id);
    setLoopStatus({ state: "idle", mode: null });
    setError(null);
    setModelError(null);
    setLoading(Boolean(connection && chat));
    if (!connection || !chat) return;
    const client = new QwenPawClient(connection);
    const [config, modelCatalog, active, loops, status, preference] =
      await Promise.allSettled([
        client.getRunningConfig(),
        client.listProviders(),
        client.getActiveModel(connection.agentId),
        client.listLoopModes(),
        client.getLoopStatus(chat.id, chat.session_id),
        loadSessionControls(connection, chat),
      ]);
    if (revision !== loadRevision.current) return;
    if (config.status === "fulfilled") {
      setRunningApproval(normalizeApprovalLevel(config.value.approval_level));
    }
    if (modelCatalog.status === "fulfilled") {
      setProviders(modelCatalog.value);
    } else {
      setModelError(errorMessage(modelCatalog.reason));
    }
    if (active.status === "fulfilled") setActiveModel(active.value);
    if (loops.status === "fulfilled") {
      setLoopModes(normalizeLoopModes(loops.value));
    }
    if (status.status === "fulfilled") setLoopStatus(status.value);
    if (preference.status === "fulfilled") {
      setSessionApproval(preference.value.approvalLevel);
      setSessionModelOverride(preference.value.modelOverride);
    }
    const failure = [config, modelCatalog, active, loops, status]
      .find((result) => result.status === "rejected");
    setError(failure?.status === "rejected"
      ? errorMessage(failure.reason)
      : null);
    setLoading(false);
  }, [chat, connection]);

  const refreshLoopStatus = useCallback(async () => {
    if (!connection || !chat) return;
    const revision = loadRevision.current;
    try {
      const value = await new QwenPawClient(connection).getLoopStatus(
        chat.id,
        chat.session_id,
      );
      if (revision !== loadRevision.current) return;
      setLoopStatus(value);
    } catch {
      // Keep the last known status while the QwenPaw reconnects.
    }
  }, [chat, connection]);

  useFocusEffect(useCallback(() => {
    let active = true;
    void load();
    const timer = setInterval(() => {
      if (active) void refreshLoopStatus();
    }, 3000);
    return () => {
      active = false;
      loadRevision.current += 1;
      clearInterval(timer);
    };
  }, [load, refreshLoopStatus]));

  const updateApproval = useCallback(async (value: ApprovalLevel | null) => {
    if (!connection || !chat) return;
    setSessionApproval(value);
    await saveSessionApprovalLevel(connection, chat, value);
  }, [chat, connection]);

  const updateModel = useCallback(async (
    value: ModelSlotOverride | null,
  ) => {
    if (!connection || !chat) return;
    setSavingModel(true);
    try {
      if (value && !activeModel?.active_llm) {
        const activated = await new QwenPawClient(connection)
          .setAgentActiveModel(connection.agentId, value);
        setActiveModel(activated);
      }
      setSessionModelOverride(value);
      await saveSessionModelOverride(connection, chat, value);
    } finally {
      setSavingModel(false);
    }
  }, [activeModel?.active_llm, chat, connection]);

  const selectedLoopMode = useMemo(
    () => loopModes.find((mode) => mode.id === selectedLoopId) ?? DEFAULT_LOOP_MODE,
    [loopModes, selectedLoopId],
  );
  const beginSubmission = useCallback(() => {
    const mode = loopStatus.state === "idle" ? selectedLoopMode : DEFAULT_LOOP_MODE;
    if (mode.id !== DEFAULT_LOOP_MODE.id) {
      setLoopStatus({ state: "starting", mode });
      setSelectedLoopId(DEFAULT_LOOP_MODE.id);
    }
    return mode;
  }, [loopStatus.state, selectedLoopMode]);

  return {
    activeModel,
    beginSubmission,
    effectiveApproval: sessionApproval ?? runningApproval,
    effectiveModel: sessionModelOverride ?? activeModel?.active_llm ?? null,
    error,
    loading,
    loopModes,
    loopStatus,
    modelError,
    providers: selectableProviders(providers),
    reload: load,
    runningApproval,
    savingModel,
    selectedLoopMode,
    sessionApproval,
    sessionModelOverride,
    setSelectedLoopId,
    updateApproval,
    updateModel,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "会话控制加载失败";
}

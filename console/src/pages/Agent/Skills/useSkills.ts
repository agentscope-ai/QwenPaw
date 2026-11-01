import { useState, useEffect, useCallback, useRef } from "react";
import { Modal } from "@agentscope-ai/design";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type { SecurityScanErrorResponse } from "../../../api/modules/security";
import { invalidateSkillCache } from "../../../api/modules/skill";
import type { SkillSpec } from "../../../api/types";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import {
  harnessApi,
  type HarnessDiscoveredSkill,
} from "../../../api/modules/harness";
import { parseErrorDetail } from "../../../utils/error";
import {
  handleScanError,
  checkScanWarnings as checkScanWarningsShared,
  showScanErrorModal,
} from "../../../utils/scanError";
import { subscribeToSkillChanges } from "../../../utils/skillChangeEvents";

type SkillActionResult =
  | { success: true; name?: string; imported?: string[] }
  | {
      success: false;
      conflict?: {
        suggested_name?: string;
        skill_name?: string;
        conflicts?: { suggested_name?: string; skill_name?: string }[];
      };
    };

export type SkillMutationOwner = {
  agentId: string;
  generation: number;
};

type SkillMutationToken = SkillMutationOwner & { token: number };

function currentAgentId() {
  return useAgentStore.getState().selectedAgent || "default";
}

export function useSkills() {
  const { t } = useTranslation();
  const { selectedAgent, agents } = useAgentStore();
  const selectedAgentInfo = agents.find((item) => item.id === selectedAgent);
  const selectedBackend = selectedAgentInfo?.backend ?? "qwenpaw";
  const canDiscoverProviderSkills = Boolean(
    selectedAgentInfo?.backend_capabilities?.provider_skills_discovery,
  );
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [providerSkills, setProviderSkills] = useState<
    HarnessDiscoveredSkill[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<{
    agentId: string;
    value: unknown;
  } | null>(null);
  const [loadedAgent, setLoadedAgent] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [importing, setImporting] = useState(false);
  const importTaskRef = useRef<{
    taskId: string;
    mutation: SkillMutationToken;
  } | null>(null);
  const importCancelReasonRef = useRef<"manual" | "timeout" | null>(null);
  const requestGenerationRef = useRef(0);
  const mutationGenerationRef = useRef(0);
  const mutationTokenRef = useRef(0);
  const activeMutationTokensRef = useRef(new Set<number>());
  const uploadTokenRef = useRef<number | null>(null);
  const importTokenRef = useRef<number | null>(null);
  const loadedAgentRef = useRef<string | null>(null);
  const { message } = useAppMessage();

  const captureMutationOwner = useCallback((): SkillMutationOwner | null => {
    const agentId = currentAgentId();
    if (
      loadedAgent === null ||
      loadedAgent !== agentId ||
      loadedAgentRef.current !== agentId
    ) {
      return null;
    }
    return { agentId, generation: mutationGenerationRef.current };
  }, [loadedAgent]);

  const ownsMutationOwner = useCallback((owner: SkillMutationOwner) => {
    return (
      owner.generation === mutationGenerationRef.current &&
      owner.agentId === currentAgentId() &&
      loadedAgentRef.current === owner.agentId
    );
  }, []);

  const beginMutation = useCallback((): SkillMutationToken | null => {
    const owner = captureMutationOwner();
    if (!owner) return null;
    const token = ++mutationTokenRef.current;
    activeMutationTokensRef.current.add(token);
    return { ...owner, token };
  }, [captureMutationOwner]);

  const ownsMutation = useCallback(
    (mutation: SkillMutationToken) =>
      activeMutationTokensRef.current.has(mutation.token) &&
      ownsMutationOwner(mutation),
    [ownsMutationOwner],
  );

  const finishMutation = useCallback((mutation: SkillMutationToken) => {
    activeMutationTokensRef.current.delete(mutation.token);
  }, []);

  const handleError = useCallback(
    (error: unknown, defaultMsg: string): boolean => {
      if (handleScanError(error, t)) return true;
      const msg =
        error instanceof Error && error.message ? error.message : defaultMsg;
      console.error(defaultMsg, error);
      message.error(msg);
      return false;
    },
    [message, t],
  );

  const checkScanWarnings = useCallback(
    (skillName: string, mutation: SkillMutationToken) =>
      checkScanWarningsShared(
        skillName,
        api.getBlockedHistory,
        api.getSkillScanner,
        t,
        () => ownsMutation(mutation),
      ),
    [ownsMutation, t],
  );

  const loadSkillsForAgent = useCallback(
    async (
      requestedAgent: string,
      requestedBackend: string,
      discoverProviderSkills: boolean,
      hardRefresh = false,
    ) => {
      if (currentAgentId() !== requestedAgent) return;
      const generation = ++requestGenerationRef.current;
      const isCurrentRequest = () =>
        generation === requestGenerationRef.current &&
        currentAgentId() === requestedAgent;

      loadedAgentRef.current = null;
      setLoadedAgent(null);
      setLoading(true);
      setLoadError(null);
      setProviderSkills([]);
      try {
        if (hardRefresh) invalidateSkillCache({ agentId: requestedAgent });
        const data = hardRefresh
          ? await api.refreshSkills(requestedAgent)
          : await api.listSkills(requestedAgent);
        if (!isCurrentRequest()) return;

        let discoveredSkills: HarnessDiscoveredSkill[] = [];
        if (requestedBackend !== "qwenpaw" && discoverProviderSkills) {
          try {
            const result = await harnessApi.listSkills(requestedBackend);
            if (!isCurrentRequest()) return;
            discoveredSkills = result.skills;
            if (result.message) message.warning(result.message);
          } catch (providerError) {
            if (!isCurrentRequest()) return;
            console.warn("Failed to discover Provider Skills:", providerError);
          }
        }

        if (!isCurrentRequest()) return;
        setSkills(data || []);
        setProviderSkills(discoveredSkills);
        loadedAgentRef.current = requestedAgent;
        setLoadedAgent(requestedAgent);
      } catch (loadError) {
        if (!isCurrentRequest()) return;
        console.error(
          t(hardRefresh ? "skills.refreshFailed" : "skills.loadFailed"),
          loadError,
        );
        setLoadError({
          agentId: requestedAgent,
          value:
            loadError instanceof Error
              ? loadError
              : new Error(t("skills.loadFailed")),
        });
        message.error(
          t(hardRefresh ? "skills.refreshFailed" : "skills.loadFailed"),
        );
      } finally {
        if (isCurrentRequest()) setLoading(false);
      }
    },
    [message, t],
  );

  const fetchSkills = useCallback(
    () =>
      loadSkillsForAgent(
        selectedAgent || "default",
        selectedBackend,
        canDiscoverProviderSkills,
      ),
    [
      canDiscoverProviderSkills,
      loadSkillsForAgent,
      selectedAgent,
      selectedBackend,
    ],
  );

  const hardRefresh = useCallback(
    () =>
      loadSkillsForAgent(
        selectedAgent || "default",
        selectedBackend,
        canDiscoverProviderSkills,
        true,
      ),
    [
      canDiscoverProviderSkills,
      loadSkillsForAgent,
      selectedAgent,
      selectedBackend,
    ],
  );

  // Invalidate cache when agent changes
  useEffect(() => {
    mutationGenerationRef.current += 1;
    activeMutationTokensRef.current.clear();
    uploadTokenRef.current = null;
    importTokenRef.current = null;
    importTaskRef.current = null;
    importCancelReasonRef.current = null;
    setUploading(false);
    setImporting(false);
    invalidateSkillCache({ agentId: selectedAgent });
    void fetchSkills();
    return () => {
      requestGenerationRef.current += 1;
      loadedAgentRef.current = null;
    };
  }, [selectedAgent, fetchSkills]);

  useEffect(
    () =>
      subscribeToSkillChanges((change) => {
        if (change.agentId !== selectedAgent) return;
        invalidateSkillCache({ agentId: selectedAgent });
        void fetchSkills();
      }),
    [fetchSkills, selectedAgent],
  );

  const createSkill = async (
    name: string,
    content: string,
    config?: Record<string, unknown>,
    enable?: boolean,
  ): Promise<SkillActionResult> => {
    const mutation = beginMutation();
    if (!mutation) return { success: false };
    try {
      const result = await api.createSkill(
        name,
        content,
        config,
        enable,
        mutation.agentId,
      );
      if (!ownsMutation(mutation)) return { success: false };
      message.success(t("skills.createdSuccessfully"));
      invalidateSkillCache({ agentId: mutation.agentId });
      await fetchSkills();
      if (!ownsMutation(mutation)) return { success: false };
      await checkScanWarnings(result.name, mutation);
      if (!ownsMutation(mutation)) return { success: false };
      return { success: true, name: result.name };
    } catch (error) {
      if (!ownsMutation(mutation)) return { success: false };
      const detail = parseErrorDetail(error);
      if (detail?.suggested_name) {
        return { success: false, conflict: detail };
      }
      handleError(error, t("skills.saveFailed"));
      return { success: false };
    } finally {
      finishMutation(mutation);
    }
  };

  const uploadSkill = async (
    file: File,
    targetName?: string,
    renameMap?: Record<string, string>,
  ): Promise<SkillActionResult> => {
    const mutation = beginMutation();
    if (!mutation) return { success: false };
    try {
      uploadTokenRef.current = mutation.token;
      setUploading(true);
      const result = await api.uploadSkill(
        file,
        {
          enable: true,
          target_name: targetName,
          rename_map: renameMap,
        },
        mutation.agentId,
      );
      if (!ownsMutation(mutation)) return { success: false };
      if (result?.count > 0) {
        message.success(
          t("skills.uploadSuccess") + `: ${result.imported.join(", ")}`,
        );
        invalidateSkillCache({ agentId: mutation.agentId });
        await fetchSkills();
        if (!ownsMutation(mutation)) return { success: false };
        for (const name of result.imported) {
          await checkScanWarnings(name, mutation);
          if (!ownsMutation(mutation)) return { success: false };
        }
      }
      if (!result?.count) {
        message.warning(t("skills.uploadNoChange"));
      }
      await fetchSkills();
      if (!ownsMutation(mutation)) return { success: false };
      return { success: true, imported: result?.imported || [] };
    } catch (error) {
      if (!ownsMutation(mutation)) return { success: false };
      const detail = parseErrorDetail(error);
      if (Array.isArray(detail?.conflicts) && detail.conflicts.length > 0) {
        return { success: false, conflict: detail };
      }
      handleError(error, t("skills.uploadFailed"));
      return { success: false };
    } finally {
      if (uploadTokenRef.current === mutation.token && ownsMutation(mutation)) {
        uploadTokenRef.current = null;
        setUploading(false);
      }
      finishMutation(mutation);
    }
  };

  const importFromHub = async (
    input: string,
    targetName?: string,
  ): Promise<SkillActionResult> => {
    if (!captureMutationOwner()) return { success: false };
    const text = (input || "").trim();
    if (!text) {
      message.warning(t("skills.provideUrl"));
      return { success: false };
    }
    if (!text.startsWith("http://") && !text.startsWith("https://")) {
      message.warning(t("skills.validUrl"));
      return { success: false };
    }
    const mutation = beginMutation();
    if (!mutation) return { success: false };
    const timeoutMs = 90_000;
    const pollMs = 1_000;
    const startedAt = Date.now();
    try {
      importTokenRef.current = mutation.token;
      setImporting(true);
      importCancelReasonRef.current = null;
      const payload = {
        bundle_url: text,
        enable: true,
        target_name: targetName,
      };
      const task = await api.startHubSkillInstall(payload, mutation.agentId);
      if (!ownsMutation(mutation)) return { success: false };
      importTaskRef.current = { taskId: task.task_id, mutation };

      while (
        importTaskRef.current?.taskId === task.task_id &&
        importTaskRef.current.mutation.token === mutation.token
      ) {
        const status = await api.getHubSkillInstallStatus(
          task.task_id,
          mutation.agentId,
        );
        if (!ownsMutation(mutation)) return { success: false };

        if (status.status === "completed" && status.result?.installed) {
          message.success(
            t("skills.importedSkill", { name: status.result.name }),
          );
          invalidateSkillCache({ agentId: mutation.agentId });
          await fetchSkills();
          if (!ownsMutation(mutation)) return { success: false };
          if (status.result.name) {
            await checkScanWarnings(status.result.name, mutation);
            if (!ownsMutation(mutation)) return { success: false };
          }
          return { success: true, name: String(status.result.name || "") };
        }

        if (status.status === "failed") {
          if (
            Array.isArray(status.result?.conflicts) &&
            status.result.conflicts.length > 0
          ) {
            return { success: false, conflict: status.result };
          }
          const hubResult = status.result as
            | SecurityScanErrorResponse
            | null
            | undefined;
          if (hubResult?.type === "security_scan_failed") {
            showScanErrorModal(hubResult, t);
            return { success: false };
          }
          throw new Error(status.error || t("skills.importFailed"));
        }

        if (status.status === "cancelled") {
          message.warning(
            t(
              importCancelReasonRef.current === "timeout"
                ? "skills.importTimeout"
                : "skills.importCancelled",
            ),
          );
          return { success: false };
        }

        if (Date.now() - startedAt >= timeoutMs) {
          importCancelReasonRef.current = "timeout";
          await api.cancelHubSkillInstall(task.task_id, mutation.agentId);
          if (!ownsMutation(mutation)) return { success: false };
        }

        await new Promise((resolve) => window.setTimeout(resolve, pollMs));
        if (!ownsMutation(mutation)) return { success: false };
      }

      return { success: false };
    } catch (error) {
      if (!ownsMutation(mutation)) return { success: false };
      handleError(error, t("skills.importFailed"));
      return { success: false };
    } finally {
      if (importTokenRef.current === mutation.token && ownsMutation(mutation)) {
        importTokenRef.current = null;
        importTaskRef.current = null;
        importCancelReasonRef.current = null;
        setImporting(false);
      }
      finishMutation(mutation);
    }
  };

  const cancelImport = useCallback(() => {
    if (!importing) return;
    const task = importTaskRef.current;
    if (!task || !ownsMutation(task.mutation)) return;
    importCancelReasonRef.current = "manual";
    void api.cancelHubSkillInstall(task.taskId, task.mutation.agentId);
  }, [importing, ownsMutation]);

  const toggleEnabled = async (skill: SkillSpec) => {
    const mutation = beginMutation();
    if (!mutation) return false;
    try {
      if (skill.enabled) {
        await api.disableSkill(skill.name, mutation.agentId);
        if (!ownsMutation(mutation)) return false;
        setSkills((prev) =>
          prev.map((s) =>
            s.name === skill.name ? { ...s, enabled: false } : s,
          ),
        );
        message.success(t("skills.disabledSuccessfully"));
      } else {
        await api.enableSkill(skill.name, mutation.agentId);
        if (!ownsMutation(mutation)) return false;
        setSkills((prev) =>
          prev.map((s) =>
            s.name === skill.name ? { ...s, enabled: true } : s,
          ),
        );
        message.success(t("skills.enabledSuccessfully"));
        await checkScanWarnings(skill.name, mutation);
        if (!ownsMutation(mutation)) return false;
      }
      invalidateSkillCache({ agentId: mutation.agentId });
      return true;
    } catch (error) {
      if (!ownsMutation(mutation)) return false;
      handleError(error, t("skills.operationFailed"));
      return false;
    } finally {
      finishMutation(mutation);
    }
  };

  const deleteSkill = async (skill: SkillSpec) => {
    const owner = captureMutationOwner();
    if (!owner) return false;
    const confirmed = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: t("common.confirm"),
        content: t("skills.deleteConfirm"),
        okText: t("common.delete"),
        okType: "danger",
        cancelText: t("common.cancel"),
        onOk: () => resolve(ownsMutationOwner(owner)),
        onCancel: () => resolve(false),
      });
    });

    if (!confirmed || !ownsMutationOwner(owner)) return false;
    const mutation = beginMutation();
    if (!mutation) return false;

    try {
      const result = await api.deleteSkill(skill.name, owner.agentId);
      if (!ownsMutation(mutation)) return false;
      if (result.deleted) {
        message.success(t("skills.deleteSuccess"));
        invalidateSkillCache({ agentId: owner.agentId });
        await fetchSkills();
        return ownsMutation(mutation);
      }
    } catch (error) {
      if (!ownsMutation(mutation)) return false;
      console.error(t("skills.deleteFailed"), error);
      message.error(t("skills.deleteFailed"));
    } finally {
      finishMutation(mutation);
    }
    return false;
  };

  const currentAgent = selectedAgent || "default";
  const error = loadError?.agentId === currentAgent ? loadError.value : null;

  return {
    skills,
    providerSkills,
    loading,
    error,
    ready: !loading && error === null && loadedAgent === currentAgent,
    uploading,
    importing,
    createSkill,
    uploadSkill,
    importFromHub,
    cancelImport,
    toggleEnabled,
    deleteSkill,
    captureMutationOwner,
    ownsMutationOwner,
    refreshSkills: fetchSkills,
    hardRefresh,
  };
}

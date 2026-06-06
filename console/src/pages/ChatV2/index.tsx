import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Tooltip } from "antd";
import ModelSelector from "../Chat/ModelSelector";
import {
  ChatPageLayout,
  ApprovalOverlay,
  ModelPromptModal,
  useChatStore,
  useChatRouter,
  useMultimodalCapabilities,
  useModelCheck,
  useWhisperSpeech,
  useApprovals,
  usePlanConfig,
} from "../../components/Chat";
import type { ChatConfig, CommandSuggestion } from "../../components/Chat";
import PlanPanel from "../../components/PlanPanel";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import { chatApi } from "../../api/modules/chat";
import { useAgentStore } from "../../stores/agentStore";
import { usePlugins } from "../../plugins/PluginContext";
import { useTheme } from "../../contexts/ThemeContext";
import { getAgentDisplayName } from "../../utils/agentDisplayName";
import WhisperSpeechButton, {
  type WhisperSpeechButtonRef,
} from "../Chat/components/WhisperSpeechButton";
import type {
  UserDisplayInfo,
  AssistantDisplayInfo,
} from "../../components/Chat/context/ChatContext";

export default function ChatV2Page() {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const { selectedAgent, agents } = useAgentStore();
  const { toolRenderConfig } = usePlugins();

  // Hooks
  const { chatId, navigate } = useChatRouter(selectedAgent, {
    basePath: "/chat-v2",
  });
  const { whisperEnabled, whisperSpeechRef, handleTranscription } =
    useWhisperSpeech<WhisperSpeechButtonRef>();
  const multimodalCaps = useMultimodalCapabilities(selectedAgent);
  const { showPrompt: showModelPrompt, setShowPrompt: setShowModelPrompt } =
    useModelCheck(selectedAgent);
  const { planEnabled } = usePlanConfig(selectedAgent);
  const [planOpen, setPlanOpen] = useState(false);

  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const { approvalRequests, handleApprove, handleDeny, handleCancel } =
    useApprovals(chatId, activeSessionId);

  // Config
  const chatConfig = useMemo<ChatConfig>(
    () => ({
      apiEndpoint: getApiUrl("/console/chat"),
      headers: buildAuthHeaders(),
      enableStream: true,
      enableReconnect: true,
      maxAttachmentSize: 10,
      supportedMediaTypes: ["image/*", "video/*", "audio/*", "application/pdf"],
      userId: "default",
      channel: "console",
    }),
    [],
  );

  const currentAgent = useMemo(
    () => agents.find((a) => a.id === selectedAgent),
    [agents, selectedAgent],
  );

  const userInfo = useMemo<UserDisplayInfo>(
    () => ({ name: chatConfig.userId || "User" }),
    [chatConfig.userId],
  );

  const assistantInfo = useMemo<AssistantDisplayInfo>(
    () => ({
      name: currentAgent ? getAgentDisplayName(currentAgent, t) : "QwenPaw",
      avatar: "/qwenpaw.png",
      model: currentAgent?.active_model?.model,
    }),
    [currentAgent, t],
  );

  const commands = useMemo<CommandSuggestion[]>(() => {
    const list: CommandSuggestion[] = [
      {
        command: "/clear",
        value: "clear",
        description: t("chat.commands.clear.description", "Clear chat history"),
      },
      {
        command: "/compact",
        value: "compact",
        description: t("chat.commands.compact.description", "Compact mode"),
      },
      {
        command: "/mission",
        value: "mission",
        description: t(
          "chat.commands.mission.description",
          "Show agent mission",
        ),
      },
      {
        command: "/skills",
        value: "skills",
        description: t(
          "chat.commands.skills.description",
          "Show available skills",
        ),
      },
    ];
    if (planEnabled) {
      list.push({
        command: "/plan",
        value: "plan ",
        description: t("chat.commands.plan.description", "Create a plan"),
      });
    }
    return list;
  }, [t, planEnabled]);

  const handleUpload = useCallback(async (file: File) => {
    const res = await chatApi.uploadFile(file);
    return { url: chatApi.filePreviewUrl(res.url) };
  }, []);

  const handleError = useCallback((error: Error) => {
    console.error("[ChatV2] Stream error:", error);
  }, []);

  const whisperPrefix = whisperEnabled ? (
    <WhisperSpeechButton
      ref={whisperSpeechRef}
      onTranscription={handleTranscription}
    />
  ) : undefined;

  return (
    <>
      <ChatPageLayout
        config={chatConfig}
        agentId={selectedAgent}
        toolCards={toolRenderConfig}
        userInfo={userInfo}
        assistantInfo={assistantInfo}
        isDark={isDark}
        placeholder={t("chat.inputPlaceholder", "Ask me anything...")}
        commands={commands}
        enableAttachments
        onUpload={handleUpload}
        maxFileSize={10}
        inputPrefix={whisperPrefix}
        allowSpeech={!whisperEnabled}
        supportsMultimodal={multimodalCaps.supportsMultimodal}
        headerExtra={
          <>
            <ModelSelector />
            {planEnabled && (
              <Tooltip title={t("plan.title", "Plan")} mouseEnterDelay={0.5}>
                <button
                  onClick={() => setPlanOpen(true)}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    padding: 4,
                    display: "inline-flex",
                    alignItems: "center",
                    color: "var(--ant-color-text-secondary, #666)",
                    fontSize: 16,
                  }}
                >
                  <svg
                    width="1em"
                    height="1em"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M9 11l3 3L22 4" />
                    <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
                  </svg>
                </button>
              </Tooltip>
            )}
          </>
        }
        onError={handleError}
      />
      {planEnabled && (
        <PlanPanel open={planOpen} onClose={() => setPlanOpen(false)} />
      )}
      <ApprovalOverlay
        approvalRequests={approvalRequests}
        onApprove={handleApprove}
        onDeny={handleDeny}
        onCancel={handleCancel}
      />
      <ModelPromptModal
        open={showModelPrompt}
        isDark={isDark}
        onSkip={() => setShowModelPrompt(false)}
        onConfigure={() => {
          setShowModelPrompt(false);
          navigate("/models");
        }}
      />
    </>
  );
}

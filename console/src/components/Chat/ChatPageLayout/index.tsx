import React, { useCallback, useState } from "react";
import { Button } from "antd";
import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons";
import ChatContainer from "../ChatContainer";
import MessageList from "../MessageList";
import MessageInput from "../MessageInput";
import SessionPanel from "../SessionPanel";
import ConversationMinimap from "../ConversationMinimap";
import type { ChatConfig, ToolCardRegistry, CommandSuggestion } from "../types";
import type {
  UserDisplayInfo,
  AssistantDisplayInfo,
} from "../context/ChatContext";
import styles from "./ChatPageLayout.module.less";

export interface ChatPageLayoutProps {
  /** Chat API configuration */
  config: ChatConfig;
  /** Agent ID */
  agentId?: string;
  /** Tool card registry */
  toolCards?: ToolCardRegistry;
  /** User display info */
  userInfo?: UserDisplayInfo;
  /** Assistant display info */
  assistantInfo?: AssistantDisplayInfo;
  /** Whether dark mode is active */
  isDark?: boolean;
  /** Input placeholder */
  placeholder?: string;
  /** Slash commands */
  commands?: CommandSuggestion[];
  /** Enable file attachments */
  enableAttachments?: boolean;
  /** File upload handler */
  onUpload?: (file: File) => Promise<{ url: string }>;
  /** Max file size in MB */
  maxFileSize?: number;
  /** Prefix element for input (e.g. whisper button) */
  inputPrefix?: React.ReactNode;
  /** Whether to allow built-in speech */
  allowSpeech?: boolean;
  /** Whether multimodal input is supported */
  supportsMultimodal?: boolean;
  /** Header extra content (rendered after collapse button) */
  headerExtra?: React.ReactNode;
  /** Stream error handler */
  onError?: (error: Error) => void;
  /** Custom class name */
  className?: string;
}

const ChatPageLayout: React.FC<ChatPageLayoutProps> = ({
  config,
  agentId,
  toolCards,
  userInfo,
  assistantInfo,
  isDark = false,
  placeholder = "Type a message...",
  commands,
  enableAttachments = true,
  onUpload,
  maxFileSize = 10,
  inputPrefix,
  allowSpeech = false,
  supportsMultimodal = false,
  headerExtra,
  onError,
  className,
}) => {
  const [sessionPanelCollapsed, setSessionPanelCollapsed] = useState(false);

  const toggleCollapse = useCallback(() => {
    setSessionPanelCollapsed((prev) => !prev);
  }, []);

  return (
    <div
      className={`${styles.chatPageLayout} ${isDark ? styles.dark : ""} ${
        className || ""
      }`}
    >
      <ChatContainer
        config={config}
        agentId={agentId}
        toolCards={toolCards}
        userInfo={userInfo}
        assistantInfo={assistantInfo}
        onError={onError}
      >
        <SessionPanel
          collapsed={sessionPanelCollapsed}
          onToggleCollapse={toggleCollapse}
        />
        <div className={styles.chatMain} data-minimap-root>
          <div className={styles.chatHeader}>
            <Button
              type="text"
              size="small"
              icon={
                sessionPanelCollapsed ? (
                  <MenuUnfoldOutlined />
                ) : (
                  <MenuFoldOutlined />
                )
              }
              onClick={toggleCollapse}
              className={styles.collapseBtn}
            />
            {headerExtra}
          </div>
          <div className={styles.messageArea}>
            <MessageList />
            <ConversationMinimap isDark={isDark} />
          </div>
          <MessageInput
            placeholder={placeholder}
            commands={commands}
            enableAttachments={enableAttachments}
            onUpload={onUpload}
            maxFileSize={maxFileSize}
            prefix={inputPrefix}
            allowSpeech={allowSpeech}
            supportsMultimodal={supportsMultimodal}
          />
        </div>
      </ChatContainer>
    </div>
  );
};

export default ChatPageLayout;

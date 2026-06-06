// ---------------------------------------------------------------------------
// QwenPaw Chat Component Library
// A composable chat UI framework built on top of @agentscope-ai/chat atoms.
// ---------------------------------------------------------------------------

// Core types
export type {
  ChatMessage,
  ChatSession,
  ChatConfig,
  ChatInputData,
  MessageContent,
  MessageRole,
  MessageStatus,
  MessageMetadata,
  TextContent,
  ImageContent,
  VideoContent,
  AudioContent,
  FileContent,
  ThinkingContent,
  ToolCallContent,
  CardContent,
  ToolCardProps,
  ToolCardComponent,
  ToolCardRegistry,
  CommandSuggestion,
  SessionGroup,
  StreamResponse,
  StreamResponseMessage,
  StreamContentItem,
  StreamContentDelta,
} from "./types";

export {
  STREAM_MESSAGE_TYPES,
  TOOL_INPUT_TYPES,
  TOOL_OUTPUT_TYPES,
} from "./types";

// Constants
export {
  DEFAULT_USER_ID,
  DEFAULT_CHANNEL,
  DEFAULT_SESSION_NAME,
  MAX_ATTACHMENT_SIZE_MB,
  ROLES,
  MESSAGE_STATUS,
  SESSION_STATUS,
} from "./constants";

// Components
export { default as ChatContainer } from "./ChatContainer";
export type { ChatContainerProps } from "./ChatContainer";
export { default as MessageList } from "./MessageList";
export type { MessageListProps } from "./MessageList";
export { default as MessageInput } from "./MessageInput";
export type { MessageInputProps } from "./MessageInput";
export { default as SessionPanel } from "./SessionPanel";
export type { SessionPanelProps } from "./SessionPanel";
export { default as ChatPageLayout } from "./ChatPageLayout";
export type { ChatPageLayoutProps } from "./ChatPageLayout";
export { default as ApprovalOverlay } from "./ApprovalOverlay";
export type { ApprovalOverlayProps } from "./ApprovalOverlay";
export { default as ModelPromptModal } from "./ModelPromptModal";
export type { ModelPromptModalProps } from "./ModelPromptModal";

// Tool Cards
export { DefaultCard, CodeExecutionCard, CardRegistry } from "./ToolCards";

// Stores
export { useChatStore } from "./stores/chatStore";
export { useSessionStore } from "./stores/sessionStore";

// Context
export { useChatContext, ChatContext } from "./context/ChatContext";
export type {
  UserDisplayInfo,
  AssistantDisplayInfo,
} from "./context/ChatContext";
export { useMessageContext, MessageContext } from "./context/MessageContext";

// Hooks
export { useChatStream } from "./hooks/useChatStream";
export type {
  UseChatStreamOptions,
  UseChatStreamReturn,
} from "./hooks/useChatStream";
export { useChatMessages, extractText } from "./hooks/useChatMessages";
export type {
  UseChatMessagesOptions,
  UseChatMessagesReturn,
} from "./hooks/useChatMessages";
export { useChatSessions } from "./hooks/useChatSessions";
export type { UseChatSessionsReturn } from "./hooks/useChatSessions";
export {
  useIMEComposition,
  useMessageHistory,
  useCommandSuggestions,
} from "./hooks/useChatInput";
export { useToolCards } from "./hooks/useToolCards";
export type {
  UseToolCardsOptions,
  UseToolCardsReturn,
} from "./hooks/useToolCards";
export { useApprovals } from "./hooks/useApprovals";
export type { ApprovalMessageData } from "./hooks/useApprovals";
export { useMultimodalCapabilities } from "./hooks/useMultimodalCapabilities";
export type { MultimodalCaps } from "./hooks/useMultimodalCapabilities";
export { useModelCheck } from "./hooks/useModelCheck";
export { useWhisperSpeech } from "./hooks/useWhisperSpeech";
export { useChatRouter } from "./hooks/useChatRouter";
export type { UseChatRouterOptions } from "./hooks/useChatRouter";
export { usePlanConfig } from "./hooks/usePlanConfig";

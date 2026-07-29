export type CreatorSessionStatus =
  | "IDLE"
  | "RUNNING"
  | "WAITING_RUNTIME"
  | "INTERRUPT_REQUESTED"
  | "WAITING_USER_INPUT"
  | "WAITING_EXECUTION_AUTH"
  | "PENDING_REVIEW"
  | "RESUMING"
  | "CANCELLED"
  | "ERROR";

export type CreatorProgressPhase =
  | "source_ingest"
  | "source_intelligence"
  | "creative_strategy"
  | "visual_development"
  | "timeline_edit"
  | "timeline_render"
  | "post_production"
  | "review"
  | "completed";

export interface CreatorTaskProgress {
  goalId?: string | null;
  phase: CreatorProgressPhase;
  label: string;
  latestMilestone?: string | null;
  completed?: number | null;
  total?: number | null;
  timelineId?: string | null;
  elementId?: string | null;
  sourceEventSeq: number;
  updatedAt: string;
}

export interface AgentStatusBadge {
  kind: string;
  label: string;
  count?: number | null;
  actionTarget?: string | null;
}

export interface AgentStatusBarView {
  progress: CreatorTaskProgress;
  activity?: {
    runningTaskCount?: number;
    [key: string]: unknown;
  } | null;
  badges: AgentStatusBadge[];
}

export type CreatorContentPart =
  | { type: "text"; text: string }
  | {
      type: "image_url";
      image_url: { url: string };
      attachment?: { assetVersionRef?: string; mediaType?: string };
    }
  | {
      type: "video_url";
      video_url: { url: string };
      fps?: number;
      max_frames?: number;
      attachment?: { assetVersionRef?: string; mediaType?: string };
    }
  | { type: "audio" | "document"; attachment: Record<string, unknown> };

export interface CreatorSessionView {
  id: string;
  projectId: string;
  status: CreatorSessionStatus;
  activeGoalId?: string;
  lastMessageSeq: number;
  lastConsumedMessageSeq: number;
  lastEventSeq: number;
}

export interface CreatorMessage {
  messageId: string;
  messageSeq: number;
  role: "system" | "user" | "assistant" | "tool";
  content: CreatorContentPart[];
  source?: string;
  metadata: Record<string, unknown>;
  createdAt: string;
}

export interface CreatorConversation {
  conversationId: string;
  title: string;
  isDefault: boolean;
  createdAt: string;
}

export interface ConversationPage {
  items: CreatorConversation[];
  nextCursor?: number | null;
}

export interface MessagePage {
  items: CreatorMessage[];
  nextAfter?: number | null;
}

export interface CreatorSessionResponse {
  session: CreatorSessionView;
  agentStatusBar: AgentStatusBarView;
}

export interface SendCreatorMessageRequest {
  clientMessageId: string;
  creatorSessionId?: string;
  conversationId: string;
  message?: string;
  content?: CreatorContentPart[];
  assetVersionRefs?: string[];
  context?: Record<string, unknown>;
}

export interface MessageAccepted {
  messageSeq: number;
  eventSeq: number;
  classification:
    | "read_only_question"
    | "mutation_instruction"
    | "review_comment"
    | "review_revise"
    | "workspace_command";
  appendState: "appended" | "queued_until_message_boundary";
  creatorSessionId: string;
  conversationId: string;
}

export interface ConversationCreated {
  conversationId: string;
  creatorSessionId: string;
  title: string;
  createdAt: string;
}

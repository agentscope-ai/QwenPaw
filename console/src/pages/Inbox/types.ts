export interface InboxSummary {
  approvals: {
    total: number;
    urgent: number;
  };
  pushMessages: {
    total: number;
    unread: number;
  };
  harvests: {
    total: number;
    active: number;
  };
}

export interface PushMessage {
  id: string;
  channelType:
    | "wechat"
    | "slack"
    | "telegram"
    | "discord"
    | "email"
    | "heartbeat";
  channelName: string;
  title: string;
  content: string;
  sender: {
    userId: string;
    username: string;
  };
  createdAt: Date;
  read: boolean;
  metadata?: {
    priority?: "low" | "normal" | "high" | "urgent";
    sourceType?: string;
    sourceId?: string;
    eventType?: string;
    status?: string;
    severity?: string;
    trigger?: string;
    durationMs?: number;
    agentId?: string;
    payload?: Record<string, unknown>;
  };
}

export interface HarvestInstance {
  id: string;
  name: string;
  templateId: string;
  emoji: string;
  schedule: {
    cron: string;
    timezone: string;
    nextRun: Date;
  };
  status: "active" | "paused" | "error";
  lastGenerated?: {
    timestamp: Date;
    success: boolean;
    previewUrl?: string;
  };
  stats: {
    totalGenerated: number;
    successRate: number;
    consecutiveDays: number;
  };
}

export interface ApprovalItem {
  id: string;
  type: "tool_call" | "config_change" | "file_access";
  title: string;
  description: string;
  requestedBy: string;
  requestedAt: Date;
  priority: "low" | "normal" | "high" | "urgent";
  status: "pending" | "approved" | "rejected";
}

export interface HarvestTemplate {
  id: string;
  name: string;
  emoji: string;
  description: string;
  estimatedReadTime: number;
  defaultSchedule: {
    cron: string;
    timezone: string;
  };
}

export type NodeStatus =
  | "todo"
  | "in_progress"
  | "done"
  | "failed"
  | "stale"
  | "abandoned"
  | "pending"
  | "not_started";

export interface FileItem {
  name: string;
  path: string;
  mime_type: string;
  size_bytes: number;
  preview_url?: string;
  download_url?: string;
}

export interface TraceItem {
  type?: string;
  data?: string;
  role?: string;
  content?: string | Array<Record<string, unknown>>;
  name?: string;
}

export interface NodeOutput {
  summary?: string;
  reasoning?: string;
  files?: FileItem[];
  trace?: TraceItem[];
}

export interface TaskNode {
  node_id: string;
  name?: string;
  description?: string;
  expected_outcome?: string;
  type?: string;
  deps?: string[];
  state: NodeStatus | string;
  trace?: TraceItem[];
  output?: NodeOutput;
  outcome?: string | null;
  error?: string | null;
  started_at?: string;
  finished_at?: string | null;
}

export interface PlanSnapshot {
  id: string;
  anchor_message_id?: string;
  user_query?: string;
  name: string;
  description?: string;
  expected_outcome?: string;
  state: string;
  created_at?: string;
  finished_at?: string | null;
  outcome?: string | null;
  nodes: Record<string, TaskNode>;
}

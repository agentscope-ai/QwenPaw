export interface TraceItem {
  /** 前端兼容格式：trace 类型 */
  type?: 'thinking' | 'text' | 'plan';
  /** 前端兼容格式：trace 数据 */
  data?: string;
  /** 后端 Msg 序列化格式：角色 */
  role?: string;
  /** 后端 Msg 序列化格式：内容 */
  content?: string;
  /** 后端 Msg 序列化格式：名称 */
  name?: string;
  node_id?: string;
  is_final?: boolean;
  summary_file?: string;
}

export interface FileItem {
  name: string;
  path: string;
  mime_type: string;
  size_bytes: number;
  content?: string;
  preview_url?: string;
  download_url?: string;
  graph_id?: string;
  node_id?: string;
}

export interface NodeOutput {
  data_ref?: string | null;
  reasoning?: string;
  summary?: string;
  files?: FileItem[] | null;
  trace?: TraceItem[];
}

export type NodeStatus = 'todo' | 'in_progress' | 'done' | 'failed' | 'stale' | 'abandoned';

export interface TaskNode {
  node_id: string;
  name?: string;
  description?: string;
  expected_outcome?: string;
  type?: string; // 'get_data' | 'analysis' | 'report' | ...
  deps?: string[];
  state: NodeStatus;
  started_at?: string;
  finished_at?: string | null;
  output?: NodeOutput;
  outcome?: string | null;
  error?: string | null;
}

export interface PlanSnapshot {
  id: string;
  anchor_message_id?: string;
  user_query?: string;
  name: string;
  description?: string;
  expected_outcome?: string;
  state: string; // 'todo' | 'in_progress' | 'done' | 'failed'
  created_at?: string;
  finished_at?: string | null;
  outcome?: string | null;
  nodes: Record<string, TaskNode>;
}

/** SSE 对话流事件（按时序保存，用于节点抽屉实时跟随） */
export type StreamEvent =
  | { type: 'text'; text: string; msg_id?: string }
  | { type: 'tool_call'; call_id: string; name: string; arguments: string; output?: string }
  | { type: 'thinking'; thinking: string };

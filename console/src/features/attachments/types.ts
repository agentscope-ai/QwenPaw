export type AttachmentLifecycle = "temporary" | "saved" | "deleted";

export interface AttachmentListItem {
  id: string;
  agent_id: string;
  conversation_id: string | null;
  message_id: string | null;
  original_name: string;
  media_type: string;
  size: number;
  lifecycle: AttachmentLifecycle;
  saved_path: string | null;
  saved_at: string | null;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  download_url: string | null;
  can_save: boolean;
  can_move: boolean;
  can_delete: boolean;
}

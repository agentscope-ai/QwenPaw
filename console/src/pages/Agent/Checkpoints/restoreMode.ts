import type { CheckpointStatus } from "@/api/types/checkpoints";

export const restoreCreatesNewChat = (
  status: CheckpointStatus | null,
): boolean => status?.restore_mode === "new_chat";

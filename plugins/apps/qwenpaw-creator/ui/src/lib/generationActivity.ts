import type { TaskView } from "@/contracts/creator";

function activeTask(task: TaskView): boolean {
  return task.status === "RUNNING" || task.status === "QUEUED";
}

/** In-flight generation for a work-graph node — regenerating while the
    provider is already painting is ambiguous, so pills must wait. */
export function nodeGenerating(
  tasks: TaskView[],
  nodeId: string | null,
): boolean {
  if (!nodeId) return false;
  if (nodeId.startsWith("visual:")) {
    // Entity ids may contain colons (char:hero): reconstruct the node-id
    // prefix from each task's target instead of splitting the node id.
    return tasks.some(
      (task) =>
        task.kind === "image_generation" &&
        activeTask(task) &&
        task.targetRef.startsWith("asset:") &&
        nodeId.startsWith(`visual:${task.targetRef.slice("asset:".length)}:`),
    );
  }
  const cut = nodeId.indexOf(":");
  const prefix = nodeId.slice(0, cut);
  const rest = nodeId.slice(cut + 1);
  const expected: [TaskView["kind"], string] | null =
    prefix === "lineup"
      ? ["image_generation", `lineup:${rest}`]
      : prefix === "storyboard"
      ? ["image_generation", `element:${rest}`]
      : prefix === "video"
      ? ["r2v_generation", `element:${rest}`]
      : null;
  if (!expected) return false;
  return tasks.some(
    (task) =>
      task.kind === expected[0] &&
      task.targetRef === expected[1] &&
      activeTask(task),
  );
}

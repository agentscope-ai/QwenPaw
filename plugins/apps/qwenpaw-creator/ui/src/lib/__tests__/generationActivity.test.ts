import { describe, expect, it } from "vitest";
import type { TaskView } from "@/contracts/creator";
import { nodeGenerating } from "../generationActivity";

const task = (kind: TaskView["kind"], targetRef: string): TaskView =>
  ({
    id: "task-1",
    kind,
    targetRef,
    status: "RUNNING",
    progress: null,
    resultRefs: [],
  }) as unknown as TaskView;

describe("nodeGenerating", () => {
  it("matches visual nodes whose entity ids contain colons", () => {
    // CR 2026-09-11: char:hero was truncated to char, so the pill never
    // locked while asset:char:hero was rendering.
    const tasks = [task("image_generation", "asset:char:hero")];
    expect(nodeGenerating(tasks, "visual:char:hero:var:x")).toBe(true);
    expect(nodeGenerating(tasks, "visual:char:heroine:var:x")).toBe(false);
  });

  it("matches element and lineup targets without splitting their ids", () => {
    expect(
      nodeGenerating(
        [task("r2v_generation", "element:elem:shot3")],
        "video:elem:shot3",
      ),
    ).toBe(true);
    expect(
      nodeGenerating(
        [task("image_generation", "lineup:cast:main")],
        "lineup:cast:main",
      ),
    ).toBe(true);
  });
});

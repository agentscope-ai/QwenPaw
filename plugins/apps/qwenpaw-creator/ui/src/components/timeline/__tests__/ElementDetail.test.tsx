import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ElementDetail from "@/components/timeline/ElementDetail";
import { projectDocument } from "@/test/creatorFixtures";
import type {
  ProjectDocument,
  TimelineDocument,
  TimelineElementDocument,
} from "@/contracts/creator";

function setup(elementId: string) {
  const project = structuredClone(projectDocument) as ProjectDocument;
  const timeline = project.timelines.items["timeline:main"] as TimelineDocument;
  const element = timeline.elements_by_id[elementId] as TimelineElementDocument;
  const utils = render(
    <ElementDetail
      project={project}
      timeline={timeline}
      element={element}
      tasks={[]}
      applying={false}
      dirtyCount={0}
      conflictPaths={[]}
      onClose={vi.fn()}
      onChange={vi.fn()}
      onApply={vi.fn()}
      onDiscard={vi.fn()}
      onAcceptConflicts={vi.fn()}
      onOpenWorkbench={vi.fn()}
    />,
  );
  const advanced = utils.container.querySelector(
    "[data-element-detail-advanced]",
  ) as HTMLDetailsElement | null;
  const summary = advanced?.querySelector("summary");
  if (summary) fireEvent.click(summary);
  return { ...utils, advanced };
}

/**
 * CR #252 P1: the guard on the numeric start / duration / z-index block was
 * inverted — the fields the caption editor is meant to drop showed up for
 * captions instead, while video and audio elements lost them.
 */
describe("ElementDetail advanced time/layer editors", () => {
  it("hides the numeric time/layer fields for a caption overlay", () => {
    const { advanced } = setup("overlay-title");
    expect(advanced).not.toBeNull();
    expect(advanced!.textContent).not.toContain("时间与层");
  });

  it("keeps the numeric time/layer fields for a non-caption element", () => {
    const { advanced } = setup("r2v-window");
    expect(advanced).not.toBeNull();
    expect(advanced!.textContent).toContain("时间与层");
  });
});
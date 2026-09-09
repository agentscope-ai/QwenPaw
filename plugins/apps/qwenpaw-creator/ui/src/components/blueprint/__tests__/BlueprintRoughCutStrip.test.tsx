import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BlueprintRoughCutStrip from "@/components/blueprint/BlueprintRoughCutStrip";
import { projectDocument } from "@/test/creatorFixtures";
import type { ProjectDocument } from "@/contracts/creator";

function cloneProject(): ProjectDocument {
  return structuredClone(projectDocument);
}

/**
 * A whole film only exists for a single live timeline whose render slot
 * carries a fresh, user-selected video version (the selector's contract).
 * Trim the fixture to its first episode; `final-v1` is that slot's
 * currently selected, non-stale render.
 */
function withWholeFilm(project: ProjectDocument): ProjectDocument {
  project.timelines.order = ["timeline:main"];
  return project;
}

function renderStrip(project: ProjectDocument) {
  return render(
    <BlueprintRoughCutStrip project={project} onSelectTimeline={vi.fn()} />,
  );
}

describe("BlueprintRoughCutStrip whole-film preview", () => {
  it("offers no whole-film chip before a final_video is composed", () => {
    const { container } = renderStrip(cloneProject());
    expect(container.querySelector("[data-blueprint-roughcut]")).toBeTruthy();
    expect(container.querySelector("[data-roughcut-play-film]")).toBeNull();
  });

  it("plays the entire composed film in the floating cinema overlay", () => {
    const { container, baseElement, getByText } = renderStrip(
      withWholeFilm(cloneProject()),
    );

    const chip = container.querySelector("[data-roughcut-play-film]");
    expect(chip).toBeTruthy();
    fireEvent.click(chip!);

    // The player is a near-fullscreen overlay portaled to <body>, not an
    // inline expansion inside the strip.
    expect(container.querySelector("[data-roughcut-cinema]")).toBeNull();
    const overlay = baseElement.querySelector("[data-roughcut-cinema]");
    expect(overlay).toBeTruthy();
    const video = baseElement.querySelector<HTMLVideoElement>(
      "[data-roughcut-player] video",
    );
    expect(video).toBeTruthy();
    // Streams the final film artifact, not a per-timeline draft rough cut.
    expect(video!.getAttribute("src")).toContain("/media/artifacts/final-v1");
    expect(getByText("测试项目 · 成片")).toBeInTheDocument();

    // Toggling the chip again closes the player.
    fireEvent.click(chip!);
    expect(baseElement.querySelector("[data-roughcut-cinema]")).toBeNull();
  });

  it("closes the cinema overlay on Escape and on backdrop click", () => {
    const { container, baseElement } = renderStrip(
      withWholeFilm(cloneProject()),
    );
    const chip = container.querySelector("[data-roughcut-play-film]");

    fireEvent.click(chip!);
    expect(baseElement.querySelector("[data-roughcut-cinema]")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(baseElement.querySelector("[data-roughcut-cinema]")).toBeNull();

    fireEvent.click(chip!);
    const backdrop = baseElement.querySelector("[data-roughcut-cinema]");
    expect(backdrop).toBeTruthy();
    // Clicking the video frame itself must NOT close the overlay…
    fireEvent.click(baseElement.querySelector("[data-roughcut-player]")!);
    expect(baseElement.querySelector("[data-roughcut-cinema]")).toBeTruthy();
    // …but clicking the scrim backdrop does.
    fireEvent.click(backdrop!);
    expect(baseElement.querySelector("[data-roughcut-cinema]")).toBeNull();
  });

  it("opens the same floating overlay from a per-timeline play chip", () => {
    const { container, baseElement } = renderStrip(cloneProject());
    const chip = container.querySelector(
      "[data-roughcut-play]",
    ) as HTMLElement | null;
    expect(chip).toBeTruthy();
    fireEvent.click(chip!);
    const video = baseElement.querySelector<HTMLVideoElement>(
      "[data-roughcut-cinema] video",
    );
    expect(video).toBeTruthy();
  });

  it("keeps the whole-film entry even when the shots-only filter leaves no frames", () => {
    // a290de0e regression shape: every element filtered out of the strip
    // (e.g. overlay/audio/interaction-only timelines) must not hide the
    // 成片 entry point along with the frames.
    const project = withWholeFilm(cloneProject());
    for (const timeline of Object.values(project.timelines.items)) {
      for (const element of Object.values(timeline.elements_by_id)) {
        element.enabled = false;
      }
    }
    const { container } = renderStrip(project);
    expect(container.querySelectorAll("[data-roughcut-frame]")).toHaveLength(0);
    expect(container.querySelector("[data-roughcut-play-film]")).toBeTruthy();
  });
});

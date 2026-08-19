import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AssetMediaPreview from "@/components/assets/AssetMediaPreview";

/**
 * Audio assets have no visual frame: a ready track must render as a waveform
 * silhouette instead of the blank "暂无预览" placeholder, while unready audio
 * keeps reporting its ingest state.
 */

describe("AssetMediaPreview audio waveform", () => {
  it("renders a waveform for ready audio instead of a blank placeholder", () => {
    const { container } = render(
      <AssetMediaPreview
        name="旁白 v1"
        mediaType="audio"
        previewUrl="http://media.test/audio.wav"
        state="ready"
        mediaClassName="media"
        placeholderClassName="placeholder"
      />,
    );
    const waveform = container.querySelector(
      '[data-asset-preview-kind="audio-waveform"]',
    );
    expect(waveform).toBeTruthy();
    expect(waveform?.querySelectorAll("i").length).toBeGreaterThan(10);
    expect(screen.queryByText("暂无预览")).not.toBeInTheDocument();
  });

  it("keeps the ingest-state placeholder for audio that is not ready yet", () => {
    const { container } = render(
      <AssetMediaPreview
        name="旁白 v1"
        mediaType="audio"
        state="processing"
        mediaClassName="media"
        placeholderClassName="placeholder"
      />,
    );
    expect(
      container.querySelector('[data-asset-preview-kind="audio-waveform"]'),
    ).toBeNull();
    expect(screen.getByText("入库中")).toBeInTheDocument();
  });
});

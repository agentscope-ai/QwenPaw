import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RichFileReferenceInput, {
  RichFileReferenceInputProvider,
} from "./RichFileReferenceInput";
import "../../i18n";

describe("RichFileReferenceInput", () => {
  it("shows only atomic chips while preserving the raw submitted value", async () => {
    const raw = "/work/app.ts:7-9\n```typescript\nconst ready = true;\n```";
    const onOpenReference = vi.fn();
    const { container } = render(
      <RichFileReferenceInputProvider onOpenReference={onOpenReference}>
        <RichFileReferenceInput value={raw} onChange={vi.fn()} />
      </RichFileReferenceInputProvider>,
    );

    expect(
      await screen.findByRole("button", { name: "app.ts · 7–9" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Code snippet · 1 line/i }),
    ).toBeInTheDocument();

    const editor = container.querySelector('[contenteditable="true"]');
    expect(editor).not.toHaveTextContent("/work/app.ts");
    expect(container.querySelector("textarea")).toHaveValue(raw);
  });

  it("clears the visible editor when the sender value is cleared", async () => {
    const { container, rerender } = render(
      <RichFileReferenceInputProvider onOpenReference={vi.fn()}>
        <RichFileReferenceInput value="@ /work/app.ts" onChange={vi.fn()} />
      </RichFileReferenceInputProvider>,
    );
    expect(
      await screen.findByRole("button", { name: "app.ts" }),
    ).toBeInTheDocument();

    rerender(
      <RichFileReferenceInputProvider onOpenReference={vi.fn()}>
        <RichFileReferenceInput value="" onChange={vi.fn()} />
      </RichFileReferenceInputProvider>,
    );

    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "app.ts" }),
      ).not.toBeInTheDocument();
    });
    expect(
      container.querySelector('[contenteditable="true"]'),
    ).toHaveTextContent("");
    expect(container.querySelector("textarea")).toHaveValue("");
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RichFileReferenceInput, {
  RichFileReferenceInputProvider,
} from "./RichFileReferenceInput";
import {
  clearLastEditorCopy,
  setLastEditorCopy,
} from "../Coding/lastEditorCopy";
import { useState } from "react";
import "../../i18n";

function ControlledRichInput() {
  const [value, setValue] = useState("");
  return (
    <RichFileReferenceInputProvider onOpenReference={vi.fn()}>
      <RichFileReferenceInput
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
    </RichFileReferenceInputProvider>
  );
}

describe("RichFileReferenceInput", () => {
  afterEach(() => clearLastEditorCopy());

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

  it("turns a whole-line Monaco paste into an atomic line reference", async () => {
    setLastEditorCopy({
      text: "const ready = true;",
      formatted: "/work/app.ts:7",
      ts: Date.now(),
    });
    const { container } = render(<ControlledRichInput />);
    const editor = container.querySelector(
      '[contenteditable="true"]',
    ) as HTMLElement;
    editor.focus();

    fireEvent.paste(editor, {
      clipboardData: {
        getData: (type: string) =>
          type === "text/plain" ? "const ready = true;" : "",
      },
    });

    expect(
      await screen.findByRole("button", { name: "app.ts · 7" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Code snippet/i }),
    ).not.toBeInTheDocument();
    await waitFor(() => {
      expect(container.querySelector("textarea")).toHaveValue("/work/app.ts:7");
    });
  });

  it("turns a partial-line Monaco paste into line and code chips", async () => {
    const formatted = "/work/app.ts:7\n```typescript\nready = true\n```";
    setLastEditorCopy({
      text: "ready = true",
      formatted,
      ts: Date.now(),
    });
    const { container } = render(<ControlledRichInput />);
    const editor = container.querySelector(
      '[contenteditable="true"]',
    ) as HTMLElement;
    editor.focus();

    fireEvent.paste(editor, {
      clipboardData: {
        getData: (type: string) =>
          type === "text/plain" ? "ready = true" : "",
      },
    });

    expect(
      await screen.findByRole("button", { name: "app.ts · 7" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Code snippet · 1 line/i }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(container.querySelector("textarea")).toHaveValue(formatted);
    });
  });
});

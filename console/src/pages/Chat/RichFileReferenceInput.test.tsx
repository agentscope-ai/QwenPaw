import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RichFileReferenceInput from "./RichFileReferenceInput";
import {
  clearLastEditorCopy,
  setLastEditorCopy,
} from "../Coding/lastEditorCopy";
import { useState } from "react";
import "../../i18n";

function ControlledRichInput() {
  const [value, setValue] = useState("");
  return (
    <RichFileReferenceInput
      value={value}
      onChange={(event) => setValue(event.target.value)}
    />
  );
}

describe("RichFileReferenceInput", () => {
  afterEach(() => clearLastEditorCopy());

  it("shows only atomic chips while preserving the raw submitted value", async () => {
    const raw = "/work/app.ts:7-9\n```typescript\nconst ready = true;\n```";
    const { container } = render(
      <RichFileReferenceInput value={raw} onChange={vi.fn()} />,
    );

    const fileChip = await screen.findByText("app.ts · 7–9");
    expect(fileChip).toBeInTheDocument();
    expect(fileChip.closest("button")).toBeNull();
    expect(
      screen.getByRole("button", { name: /Code snippet · 1 line/i }),
    ).toBeInTheDocument();

    const editor = container.querySelector('[contenteditable="true"]');
    expect(editor).not.toHaveTextContent("/work/app.ts");
    expect(container.querySelector("textarea")).toHaveValue(raw);
  });

  it("clears the visible editor when the sender value is cleared", async () => {
    const { container, rerender } = render(
      <RichFileReferenceInput value="@ /work/app.ts" onChange={vi.fn()} />,
    );
    expect(await screen.findByText("app.ts")).toBeInTheDocument();

    rerender(<RichFileReferenceInput value="" onChange={vi.fn()} />);

    await waitFor(() => {
      expect(screen.queryByText("app.ts")).not.toBeInTheDocument();
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

    expect(await screen.findByText("app.ts · 7")).toBeInTheDocument();
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

    expect(await screen.findByText("app.ts · 7")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Code snippet · 1 line/i }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(container.querySelector("textarea")).toHaveValue(formatted);
    });
  });
});

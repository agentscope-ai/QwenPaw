/**
 * Unit tests for ImportButton, the hidden file input plus its trigger button.
 *
 * Facts that shaped this suite (each one read off the source or measured):
 *
 * 1. The component wraps a hidden `<input type="file" accept=".zip">` and a
 *    button that calls `fileInputRef.current?.click()`. antd renders for real
 *    here (`Button` comes straight from `antd`), so the visible trigger is
 *    queried by role/name and the hidden input by its DOM attributes.
 * 2. The input is `style={{ display: "none" }}`, so it is deliberately not
 *    exposed to accessibility queries; it is asserted through
 *    `container.querySelector` on real attributes rather than through a role
 *    query, because that is how the component actually hides it.
 * 3. `onChange` reads `e.target.files?.[0]` and only forwards when a file is
 *    present, then clears `e.target.value = ""`. Both halves are asserted: a
 *    real file is forwarded, an empty selection is not.
 * 4. After forwarding, the input value is reset so picking the same file twice
 *    in a row still fires. That reset is the point of the second test below.
 * 5. The button's accessible name is the antd icon's aria-label glued to the
 *    i18n key ("importbackup.import"), measured from a failure dump, so the
 *    matcher is anchored on the key with a pattern rather than an exact string.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const i18nStub = vi.hoisted(() => {
  const t = (key: string) => key;
  const i18n = {
    resolvedLanguage: "en",
    changeLanguage: () => undefined,
    language: "en",
  };
  return { t, i18n };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: i18nStub.t, i18n: i18nStub.i18n }),
}));

import ImportButton from "./ImportButton";

function triggerButton() {
  // See note 5: the accessible name is icon-label + key, so anchor on the key.
  return screen.getByRole("button", { name: /backup\.import/ });
}

describe("ImportButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders a hidden zip-only file input next to the trigger button", () => {
    const { container } = render(<ImportButton onPick={vi.fn()} />);

    expect(triggerButton()).toBeInTheDocument();
    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    expect(input).toHaveAttribute("accept", ".zip");
    expect((input as HTMLInputElement).style.display).toBe("none");
  });

  it("forwards the picked file to onPick", () => {
    const onPick = vi.fn();
    const { container } = render(<ImportButton onPick={onPick} />);
    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File(["zipped"], "backup.zip", {
      type: "application/zip",
    });

    fireEvent.change(input, { target: { files: [file] } });

    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick.mock.calls[0][0]).toBe(file);
    expect((onPick.mock.calls[0][0] as File).name).toBe("backup.zip");
  });

  it("does not forward when the selection is empty", () => {
    const onPick = vi.fn();
    const { container } = render(<ImportButton onPick={onPick} />);
    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;

    fireEvent.change(input, { target: { files: [] } });

    expect(onPick).not.toHaveBeenCalled();
  });

  it("clears the input value after forwarding so the same file re-fires", () => {
    const onPick = vi.fn();
    const { container } = render(<ImportButton onPick={onPick} />);
    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File(["zipped"], "backup.zip", {
      type: "application/zip",
    });

    fireEvent.change(input, { target: { files: [file] } });
    expect(input.value).toBe("");

    fireEvent.change(input, { target: { files: [file] } });
    expect(onPick).toHaveBeenCalledTimes(2);
  });

  it("opens the file picker when the trigger button is clicked", () => {
    const { container } = render(<ImportButton onPick={vi.fn()} />);
    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const clickSpy = vi.spyOn(input, "click");

    fireEvent.click(triggerButton());

    expect(clickSpy).toHaveBeenCalledTimes(1);
    clickSpy.mockRestore();
  });
});

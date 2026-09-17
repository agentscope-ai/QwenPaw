/**
 * freeModelSwitchWarning gates switches to free models behind a
 * confirmation dialog (free tiers have weak availability guarantees).
 * The "don't show again" state must persist across sessions.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

const confirmMock = vi.fn();
vi.mock("@agentscope-ai/design", () => ({
  Modal: {
    confirm: (...args: unknown[]) => confirmMock(...args),
  },
  Checkbox: ({ children }: Record<string, unknown>) => children,
}));

import { confirmFreeModelSwitch } from "./freeModelSwitchWarning";

const WARNING_KEY = "qwenpaw_free_model_switch_warning_disabled";

const t = ((key: string) => key) as any;
const freeModel = { is_free: true };
const paidModel = { is_free: false };
const provider = { id: "openrouter" };

describe("confirmFreeModelSwitch", () => {
  beforeEach(() => {
    localStorage.clear();
    confirmMock.mockClear();
  });

  it("skips the dialog for paid models", async () => {
    await expect(
      confirmFreeModelSwitch({ provider, model: paidModel, t }),
    ).resolves.toBe(true);
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it("skips the dialog when the user disabled it previously", async () => {
    localStorage.setItem(WARNING_KEY, "1");
    await expect(
      confirmFreeModelSwitch({ provider, model: freeModel, t }),
    ).resolves.toBe(true);
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it("shows the dialog for a free model and resolves true on confirm", async () => {
    confirmMock.mockImplementation((opts: any) => {
      opts.onOk();
    });
    await expect(
      confirmFreeModelSwitch({ provider, model: freeModel, t }),
    ).resolves.toBe(true);
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(confirmMock.mock.calls[0][0].title).toBe(
      "models.freeModelWarningTitle",
    );
  });

  it("resolves false when the user cancels", async () => {
    confirmMock.mockImplementation((opts: any) => {
      opts.onCancel();
    });
    await expect(
      confirmFreeModelSwitch({ provider, model: freeModel, t }),
    ).resolves.toBe(false);
  });

  it("resolves false when the modal closes without a decision", async () => {
    confirmMock.mockImplementation((opts: any) => {
      opts.afterClose();
    });
    await expect(
      confirmFreeModelSwitch({ provider, model: freeModel, t }),
    ).resolves.toBe(false);
  });

  it("settles only once even if both cancel and afterClose fire", async () => {
    confirmMock.mockImplementation((opts: any) => {
      opts.onCancel();
      opts.afterClose();
    });
    await expect(
      confirmFreeModelSwitch({ provider, model: freeModel, t }),
    ).resolves.toBe(false);
  });

  it("persists the disable choice when the checkbox is checked", async () => {
    confirmMock.mockImplementation((opts: any) => {
      // Simulate the user checking "don't show again" via the content tree
      // The checkbox onChange is wired inside the rendered content element
      const content = opts.content;
      // Walk the element tree to find the Checkbox onChange handler
      const findCheckbox = (node: any): any => {
        if (!node) return null;
        if (node.props?.onChange) return node.props.onChange;
        const children = node.props?.children;
        if (Array.isArray(children)) {
          for (const child of children) {
            const found = findCheckbox(child);
            if (found) return found;
          }
        } else if (children) {
          return findCheckbox(children);
        }
        return null;
      };
      const onChange = findCheckbox(content);
      expect(onChange).toBeTruthy();
      onChange({ target: { checked: true } });
      opts.onOk();
    });
    await confirmFreeModelSwitch({ provider, model: freeModel, t });
    expect(localStorage.getItem(WARNING_KEY)).toBe("1");
  });

  it("uses the provider sample website for known providers", async () => {
    confirmMock.mockImplementation((opts: any) => {
      const html = JSON.stringify(opts.content);
      expect(html).toContain("https://openrouter.ai/collections/free-models");
      opts.onOk();
    });
    await confirmFreeModelSwitch({ provider, model: freeModel, t });
  });

  it("falls back to the provider base_url for unknown providers", async () => {
    confirmMock.mockImplementation((opts: any) => {
      const html = JSON.stringify(opts.content);
      expect(html).toContain("https://my-provider.example.com");
      opts.onOk();
    });
    await confirmFreeModelSwitch({
      provider: { id: "custom", base_url: "https://my-provider.example.com" },
      model: freeModel,
      t,
    });
  });

  it("falls back to '#' when neither sample nor base_url exists", async () => {
    confirmMock.mockImplementation((opts: any) => {
      const html = JSON.stringify(opts.content);
      expect(html).toContain('"#"');
      opts.onOk();
    });
    await confirmFreeModelSwitch({
      provider: { id: "mystery" },
      model: freeModel,
      t,
    });
  });
});

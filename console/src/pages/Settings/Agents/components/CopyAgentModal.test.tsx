/**
 * Unit tests for CopyAgentModal.
 *
 * The modal owns the "duplicate an agent profile" form: it prefills a name
 * derived from the source agent, exposes four copy options, and hands the
 * assembled CopyAgentRequest to onOk on confirm. These tests assert that
 * observable contract only (prefill, toggles, payload shape, cancel paths).
 *
 * Three harness notes, each established by a throwaway probe run rather than
 * assumed:
 *
 * 1. The `t` returned by the i18n mock must be render-stable. The component's
 *    prefill effect lists `t` in its dependency array, so a mock that builds a
 *    fresh arrow function per render makes that effect re-run after every
 *    render and write the prefill back over whatever the user typed. With such
 *    a mock, fireEvent.change on the name input silently has no effect and the
 *    form looks read-only. Hoisting one stable `t` fixes it, which is why the
 *    mock is defined through vi.hoisted instead of inline.
 *
 * 2. These antd Checkboxes are controlled, so the only trustworthy read of a
 *    toggle is the value the component itself carries. `fireEvent.change` with
 *    a new `checked` flips the DOM property but does NOT reach onChange: the
 *    payload still holds the default and an unrelated re-render writes the
 *    default back (both measured). `fireEvent.click` on the input, on the
 *    wrapper label and on the label's text span all do reach onChange. The
 *    helpers below therefore use `click`, and every option case is judged by
 *    two state-observable consequences - the rendered checkbox after an
 *    unrelated re-render, and the submitted payload - not by the DOM property
 *    alone.
 *
 * 3. antd surfaces a pending confirm as the `ant-btn-loading` class and leaves
 *    the button's `disabled` property false (measured on both the default and
 *    the confirmLoading render). Asserting `disabled` would be a false
 *    assertion, so the pending state is read from the class.
 *
 * The component imports Modal/Input/Checkbox/Space/Typography from "antd"
 * directly, so no design-system stub is involved: dialog presence, portal
 * behaviour and destroyOnClose are the real thing.
 */
import { describe, it, expect, vi, type Mock } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import type { AgentSummary, CopyAgentRequest } from "@/api/types/agents";
import { CopyAgentModal } from "./CopyAgentModal";

// A render-stable translator: see harness note 1.
const { translate } = vi.hoisted(() => ({
  translate: (key: string) => key,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate }),
}));

const NAME_PLACEHOLDER = "agent.namePlaceholder";
const OPTION_AGENT_JSON = "agent.copyOptionAgentJson";
const OPTION_MD_FILES = "agent.copyOptionMdFiles";
const OPTION_SKILLS = "agent.copyOptionSkills";
const OPTION_JOBS = "agent.copyOptionJobs";

function agent(id: string, name: string): AgentSummary {
  return {
    id,
    name,
    description: "",
    workspace_dir: "",
    enabled: true,
    backend: "qwenpaw",
  } as AgentSummary;
}

interface RenderArgs {
  open?: boolean;
  sourceAgent?: AgentSummary | null;
  confirmLoading?: boolean;
  onOk?: (body: CopyAgentRequest) => Promise<void> | void;
  onCancel?: () => void;
}

function renderModal({
  open = true,
  sourceAgent = agent("alpha", "Alpha"),
  confirmLoading,
  onOk = vi.fn(),
  onCancel = vi.fn(),
}: RenderArgs = {}) {
  // Omit confirmLoading entirely unless the caller sets it, so the prop's
  // default value stays exercised by every other case.
  const loadingProp = confirmLoading === undefined ? {} : { confirmLoading };
  const utils = render(
    <CopyAgentModal
      open={open}
      sourceAgent={sourceAgent}
      onOk={onOk}
      onCancel={onCancel}
      {...loadingProp}
    />,
  );
  return {
    ...utils,
    onOk: onOk as Mock,
    onCancel: onCancel as Mock,
  };
}

function nameInput(): HTMLInputElement {
  return screen.getByPlaceholderText(NAME_PLACEHOLDER) as HTMLInputElement;
}

function option(labelKey: string): HTMLInputElement {
  const boxes = screen.getAllByRole("checkbox");
  const hit = boxes.find((b) => b.closest("label")?.textContent === labelKey);
  if (!hit) {
    throw new Error(`no checkbox labelled ${labelKey}`);
  }
  return hit as HTMLInputElement;
}

function toggleOption(labelKey: string) {
  // Controlled antd Checkbox: `click` reaches onChange, `change` does not
  // (harness note 2).
  act(() => {
    fireEvent.click(option(labelKey));
  });
}

function typeName(value: string) {
  act(() => {
    fireEvent.change(nameInput(), { target: { value } });
  });
}

/**
 * Drive an unrelated controlled field so React re-renders and re-asserts every
 * controlled value from state. A toggle that only touched the DOM property is
 * undone by this; a real state change survives it.
 */
function reassertControlledValues() {
  typeName("reassert");
}

function confirmButton(): HTMLButtonElement {
  return screen
    .getByText("common.confirm")
    .closest("button") as HTMLButtonElement;
}

function cancelButton(): HTMLButtonElement {
  return screen
    .getByText("common.cancel")
    .closest("button") as HTMLButtonElement;
}

async function clickConfirm() {
  await act(async () => {
    fireEvent.click(confirmButton());
  });
}

function submitted(onOk: Mock): CopyAgentRequest {
  expect(onOk).toHaveBeenCalledTimes(1);
  return onOk.mock.calls[0][0] as CopyAgentRequest;
}

describe("CopyAgentModal", () => {
  it("renders no dialog while closed", () => {
    renderModal({ open: false });

    expect(screen.queryByPlaceholderText(NAME_PLACEHOLDER)).toBeNull();
    expect(document.body.innerHTML).not.toContain("ant-modal-title");
  });

  it("prefills the copy name from the source agent and the default options", () => {
    renderModal();

    expect(nameInput().value).toBe("Alpha Copy");
    expect(option(OPTION_MD_FILES).checked).toBe(true);
    expect(option(OPTION_SKILLS).checked).toBe(false);
    expect(option(OPTION_JOBS).checked).toBe(false);
  });

  it("locks the agent.json option and always reports it as copied", async () => {
    const { onOk } = renderModal();

    expect(option(OPTION_AGENT_JSON).checked).toBe(true);
    expect(option(OPTION_AGENT_JSON).disabled).toBe(true);

    // The lock is not merely visual: an attempt to clear it does not reach the
    // payload.
    act(() => {
      fireEvent.click(option(OPTION_AGENT_JSON));
    });
    reassertControlledValues();
    expect(option(OPTION_AGENT_JSON).checked).toBe(true);

    await clickConfirm();

    expect(submitted(onOk).copy_agent_json).toBe(true);
  });

  it("falls back to the agent id when the agent carries no name", () => {
    renderModal({ sourceAgent: agent("nameless-id", "") });

    expect(nameInput().value).toBe("nameless-id Copy");
  });

  it("uses the localized default label for the built-in default agent", () => {
    renderModal({ sourceAgent: agent("default", "Default Agent") });

    expect(nameInput().value).toBe("agent.defaultDisplayName Copy");
  });

  it("keeps a customized name for the default agent", () => {
    renderModal({ sourceAgent: agent("default", "Customized") });

    expect(nameInput().value).toBe("Customized Copy");
  });

  it("submits the prefilled defaults when the user changes nothing", async () => {
    const { onOk } = renderModal();

    await clickConfirm();

    expect(submitted(onOk)).toEqual({
      name: "Alpha Copy",
      copy_agent_json: true,
      copy_md_files: true,
      copy_skills: false,
      copy_jobs: false,
    });
  });

  it("submits the edited name and every toggled option", async () => {
    const { onOk } = renderModal();

    toggleOption(OPTION_MD_FILES);
    toggleOption(OPTION_SKILLS);
    toggleOption(OPTION_JOBS);
    reassertControlledValues();
    expect(option(OPTION_MD_FILES).checked).toBe(false);
    expect(option(OPTION_SKILLS).checked).toBe(true);
    expect(option(OPTION_JOBS).checked).toBe(true);

    typeName("Cloned Agent");
    expect(nameInput().value).toBe("Cloned Agent");

    await clickConfirm();

    expect(submitted(onOk)).toEqual({
      name: "Cloned Agent",
      copy_agent_json: true,
      copy_md_files: false,
      copy_skills: true,
      copy_jobs: true,
    });
  });

  it("keeps a toggled option after an unrelated re-render", async () => {
    const { onOk } = renderModal();

    toggleOption(OPTION_SKILLS);
    reassertControlledValues();

    await clickConfirm();

    expect(submitted(onOk).copy_skills).toBe(true);
  });

  it("supports toggling an option back off", async () => {
    const { onOk } = renderModal();

    toggleOption(OPTION_MD_FILES);
    toggleOption(OPTION_MD_FILES);
    reassertControlledValues();
    expect(option(OPTION_MD_FILES).checked).toBe(true);

    await clickConfirm();

    expect(submitted(onOk).copy_md_files).toBe(true);
  });

  it("trims surrounding whitespace from the submitted name", async () => {
    const { onOk } = renderModal();

    typeName("  Padded Name  ");

    await clickConfirm();

    expect(submitted(onOk).name).toBe("Padded Name");
  });

  it("omits the name when the field is left blank so the backend can derive one", async () => {
    const { onOk } = renderModal();

    typeName("   \t ");

    await clickConfirm();

    const body = submitted(onOk);
    // The key stays present with an undefined value rather than being dropped.
    expect(Object.keys(body)).toContain("name");
    expect(body.name).toBeUndefined();
    expect(body.copy_md_files).toBe(true);
  });

  it("awaits a promise-returning onOk without dropping the payload", async () => {
    let release: () => void = () => {};
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    const onOk: Mock = vi.fn(() => pending);
    renderModal({ onOk });

    await act(async () => {
      fireEvent.click(confirmButton());
    });

    expect(submitted(onOk).name).toBe("Alpha Copy");

    await act(async () => {
      release();
      await pending;
    });
  });

  it("reports cancellation from the cancel button and from the close icon", () => {
    const { onCancel } = renderModal();

    act(() => {
      fireEvent.click(cancelButton());
    });
    expect(onCancel).toHaveBeenCalledTimes(1);

    // antd renders the close icon as an unlabeled button; the class is its
    // stable handle here.
    const closeIcon = document.querySelector(".ant-modal-close") as HTMLElement;
    expect(closeIcon).not.toBeNull();
    act(() => {
      fireEvent.click(closeIcon);
    });
    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  it("shows the pending state on the confirm button while confirmLoading is set", () => {
    renderModal({ confirmLoading: true });

    expect(confirmButton().className).toContain("ant-btn-loading");
  });

  it("leaves the confirm button idle when confirmLoading is not provided", () => {
    renderModal();

    expect(confirmButton().className).not.toContain("ant-btn-loading");
  });

  it("keeps the dialog open but unprefilled when there is no source agent", async () => {
    const { onOk } = renderModal({ sourceAgent: null });

    // The guard only skips prefilling; it does not hide the dialog.
    expect(screen.getByPlaceholderText(NAME_PLACEHOLDER)).not.toBeNull();
    expect(nameInput().value).toBe("");

    await clickConfirm();

    expect(submitted(onOk).name).toBeUndefined();
  });

  it("restores the prefill and default options when reopened for another agent", async () => {
    const onOk = vi.fn();
    const onCancel = vi.fn();
    const { rerender } = renderModal({ onOk, onCancel });

    typeName("Mutated");
    toggleOption(OPTION_JOBS);
    expect(nameInput().value).toBe("Mutated");
    expect(option(OPTION_JOBS).checked).toBe(true);

    rerender(
      <CopyAgentModal
        open={false}
        sourceAgent={agent("alpha", "Alpha")}
        onOk={onOk}
        onCancel={onCancel}
      />,
    );
    rerender(
      <CopyAgentModal
        open
        sourceAgent={agent("beta", "Beta")}
        onOk={onOk}
        onCancel={onCancel}
      />,
    );

    expect(nameInput().value).toBe("Beta Copy");
    expect(option(OPTION_JOBS).checked).toBe(false);
    expect(option(OPTION_MD_FILES).checked).toBe(true);
    expect(option(OPTION_SKILLS).checked).toBe(false);
  });

  it("re-prefills when the source agent changes while the dialog stays open", () => {
    const { rerender } = renderModal();

    typeName("Mutated");
    expect(nameInput().value).toBe("Mutated");

    rerender(
      <CopyAgentModal
        open
        sourceAgent={agent("gamma", "Gamma")}
        onOk={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(nameInput().value).toBe("Gamma Copy");
  });

  it("does not prefill while closed and prefills once opened", () => {
    const onOk = vi.fn();
    const onCancel = vi.fn();
    const { rerender } = renderModal({
      open: false,
      sourceAgent: agent("delta", "Delta"),
      onOk,
      onCancel,
    });

    expect(screen.queryByPlaceholderText(NAME_PLACEHOLDER)).toBeNull();

    rerender(
      <CopyAgentModal
        open
        sourceAgent={agent("delta", "Delta")}
        onOk={onOk}
        onCancel={onCancel}
      />,
    );

    expect(nameInput().value).toBe("Delta Copy");
  });
});

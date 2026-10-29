// @vitest-environment jsdom
/**
 * SessionDrawer tests - the session edit drawer's user-visible contract: the
 * fixed title and the two footer buttons it always renders, the save button's
 * submit-through-form path and its saving flag, the close button's route back
 * to the caller, and the read-only identity block that appears only while a
 * session is being edited.
 *
 * Harness notes (each one a measured fact about this target, not a guess):
 *
 * 1. The shared design stub (src/test/design-mock.ts) does not export `Drawer`
 *    at all, and its `Form` is a pass-through that drops both `form` and
 *    `onFinish`. Importing them from the shared stub would yield `undefined`
 *    for the first and would make the drawer's submit contract unobservable
 *    for the second. This suite therefore supplies its own factory and leaves
 *    the shared stub untouched, because other suites depend on it.
 * 2. The product does not call `onSubmit` directly: the save button calls
 *    `form.submit()` and the `Form`'s `onFinish` carries the values up. The
 *    stub records the `onFinish` it was handed and exposes the recorded form
 *    instance, so both halves of that chain are assertable - the button really
 *    reaches `form.submit()`, and the form really reports through `onFinish`.
 * 3. `Drawer` is stubbed to render `null` when `open` is false and to expose
 *    the `onClose` it was given through a dedicated close control, plus the
 *    `width`/`placement`/`destroyOnHidden` props it was configured with. That
 *    keeps the drawer's own configuration observable without pulling in antd's
 *    portal and animation machinery.
 * 4. The identity block is gated on `editingSession` alone (not on `open`), so
 *    both arms are driven: a session present renders all four read-only fields
 *    with their values and the disabled flag, and `null` renders none of them.
 * 5. The `name` field is always rendered, including while editing, and its
 *    rule declares `required: false` - the stub records the rules per field
 *    name so that declaration stays assertable rather than silently dropped.
 * 6. Translation is stubbed to a deterministic function that folds
 *    interpolation params into the returned key, so the two footer labels can
 *    be asserted exactly.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FormInstance } from "antd";
import type { Session } from "./constants";
import { SessionDrawer } from "./SessionDrawer";
import styles from "../index.module.less";

const h = vi.hoisted(() => ({
  stableT: (key: string, arg?: unknown) => {
    if (typeof arg === "string") return `${key}::${arg}`;
    if (arg && typeof arg === "object") {
      const parts = Object.entries(arg as Record<string, unknown>)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([k, v]) => `${k}=${String(v)}`);
      return `${key}::${parts.join(",")}`;
    }
    return key;
  },
  onFinish: null as ((values: unknown) => void) | null,
  formOnDrawer: null as unknown,
  rules: {} as Record<string, unknown[]>,
  labels: {} as Record<string, string>,
  items: {} as Record<string, string>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: h.stableT, i18n: { language: "en" } }),
}));

vi.mock("@agentscope-ai/design", () => {
  const nameKey = (name: unknown) => String(name ?? "");

  const Drawer = ({
    open,
    title,
    footer,
    children,
    onClose,
    width,
    placement,
    destroyOnHidden,
  }: any) => {
    if (!open) return null;
    return (
      <div
        role="dialog"
        data-testid="session-drawer"
        data-width={String(width)}
        data-placement={String(placement)}
        data-destroy-on-hidden={destroyOnHidden ? "yes" : "no"}
      >
        <div data-testid="drawer-title">{title}</div>
        <button type="button" data-testid="drawer-x" onClick={onClose}>
          x
        </button>
        {children}
        <div data-testid="drawer-footer">{footer}</div>
      </div>
    );
  };

  const FormItem = ({ children, name, label, rules }: any) => {
    const key = nameKey(name);
    if (name !== undefined) {
      h.rules[key] = rules ?? [];
      h.labels[key] = typeof label === "string" ? label : "";
    }
    return (
      <div
        data-testid={`form-item-${
          key || (typeof label === "string" ? label : "unnamed")
        }`}
      >
        {label ? (
          <span data-testid={`label-${key || label}`}>{label}</span>
        ) : null}
        {children}
      </div>
    );
  };

  const Form = ({ children, form, onFinish, layout }: any) => {
    // Record both halves of the submit chain (note 2 above).
    h.onFinish = onFinish ?? null;
    h.formOnDrawer = form ?? null;
    return (
      <div data-testid="session-form" data-layout={String(layout)}>
        {children}
      </div>
    );
  };

  const Input = ({
    value,
    placeholder,
    disabled,
    type,
    suffix,
    onChange,
  }: any) => (
    <input
      value={value ?? ""}
      placeholder={placeholder}
      disabled={disabled}
      type={type}
      onChange={onChange}
      data-suffix={suffix ? "yes" : "no"}
    />
  );

  const Button = ({ children, onClick, type, loading }: any) => (
    <button
      type="button"
      onClick={onClick}
      data-btn-type={type ?? "default"}
      data-loading={loading ? "yes" : "no"}
    >
      {children}
    </button>
  );

  return {
    Drawer,
    Form: Object.assign(Form, { Item: FormItem }),
    Input,
    Button,
  };
});

const SESSION: Session = {
  id: "id-1",
  session_id: "sid-1",
  user_id: "user-1",
  channel: "console",
  name: "my session",
} as Session;

function makeForm(submit = vi.fn()) {
  return { submit } as unknown as FormInstance<Session>;
}

beforeEach(() => {
  h.onFinish = null;
  h.formOnDrawer = null;
  h.rules = {};
  h.labels = {};
  h.items = {};
});

describe("SessionDrawer - shell", () => {
  it("renders nothing while closed, even with a session to edit", () => {
    render(
      <SessionDrawer
        open={false}
        editingSession={SESSION}
        form={makeForm()}
        saving={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("session-drawer")).toBeNull();
  });

  it("renders the drawer with its fixed title, width and placement when open", () => {
    render(
      <SessionDrawer
        open
        editingSession={null}
        form={makeForm()}
        saving={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    const drawer = screen.getByTestId("session-drawer");
    expect(within(drawer).getByTestId("drawer-title")).toHaveTextContent(
      "sessions.editSession",
    );
    expect(drawer).toHaveAttribute("data-width", "520");
    expect(drawer).toHaveAttribute("data-placement", "right");
    expect(drawer).toHaveAttribute("data-destroy-on-hidden", "yes");
  });

  it("routes the drawer's own close control to onClose", () => {
    const onClose = vi.fn();
    render(
      <SessionDrawer
        open
        editingSession={null}
        form={makeForm()}
        saving={false}
        onClose={onClose}
        onSubmit={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("drawer-x"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders the vertical form wired to the caller's form instance", () => {
    const form = makeForm();
    render(
      <SessionDrawer
        open
        editingSession={null}
        form={form}
        saving={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByTestId("session-form")).toHaveAttribute(
      "data-layout",
      "vertical",
    );
    // The same instance the caller owns is the one the form was given.
    expect(h.formOnDrawer).toBe(form);
  });

  it("always renders the name field and keeps its rule optional", () => {
    render(
      <SessionDrawer
        open
        editingSession={null}
        form={makeForm()}
        saving={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByPlaceholderText("Session name")).toBeInTheDocument();
    expect(h.rules.name).toHaveLength(1);
    expect(h.rules.name[0]).toMatchObject({
      required: false,
      message: "Please input name",
    });
    expect(h.labels.name).toBe("name");
  });
});

describe("SessionDrawer - footer", () => {
  it("renders both footer buttons and keeps cancel routed to onClose", () => {
    const onClose = vi.fn();
    render(
      <SessionDrawer
        open
        editingSession={null}
        form={makeForm()}
        saving={false}
        onClose={onClose}
        onSubmit={vi.fn()}
      />,
    );
    const footer = screen.getByTestId("drawer-footer");
    expect(within(footer).getByText("common.cancel")).toBeInTheDocument();
    expect(within(footer).getByText("common.save")).toBeInTheDocument();
    expect(footer.firstElementChild).toHaveClass(styles.formActions);
    fireEvent.click(within(footer).getByText("common.cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("submits through the form instance rather than calling onSubmit directly", () => {
    const submit = vi.fn();
    const onSubmit = vi.fn();
    render(
      <SessionDrawer
        open
        editingSession={null}
        form={makeForm(submit)}
        saving={false}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(
      within(screen.getByTestId("drawer-footer")).getByText("common.save"),
    );
    expect(submit).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("reports the values through the form's onFinish when the form finishes", () => {
    const onSubmit = vi.fn();
    render(
      <SessionDrawer
        open
        editingSession={null}
        form={makeForm()}
        saving={false}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    // The recorded onFinish is the caller's onSubmit - the second half of the
    // submit chain (note 2 above).
    expect(h.onFinish).toBe(onSubmit);
  });

  it("mirrors the saving flag onto the save button and leaves cancel unmarked", () => {
    render(
      <SessionDrawer
        open
        editingSession={null}
        form={makeForm()}
        saving={true}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    const footer = screen.getByTestId("drawer-footer");
    expect(
      within(footer).getByText("common.save").closest("button"),
    ).toHaveAttribute("data-loading", "yes");
    expect(
      within(footer).getByText("common.cancel").closest("button"),
    ).toHaveAttribute("data-loading", "no");
  });

  it("keeps the save button unmarked while nothing is being saved", () => {
    render(
      <SessionDrawer
        open
        editingSession={null}
        form={makeForm()}
        saving={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    const footer = screen.getByTestId("drawer-footer");
    expect(
      within(footer).getByText("common.save").closest("button"),
    ).toHaveAttribute("data-loading", "no");
  });

  it("still submits while saving, because the product does not guard the click", () => {
    // What would make this red: adding `disabled={saving}` to the save button.
    const submit = vi.fn();
    render(
      <SessionDrawer
        open
        editingSession={null}
        form={makeForm(submit)}
        saving={true}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    fireEvent.click(
      within(screen.getByTestId("drawer-footer")).getByText("common.save"),
    );
    expect(submit).toHaveBeenCalledTimes(1);
  });
});

describe("SessionDrawer - identity block", () => {
  it("renders the four read-only identity fields while editing a session", () => {
    render(
      <SessionDrawer
        open
        editingSession={SESSION}
        form={makeForm()}
        saving={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByDisplayValue("id-1")).toBeDisabled();
    expect(screen.getByDisplayValue("sid-1")).toBeDisabled();
    expect(screen.getByDisplayValue("user-1")).toBeDisabled();
    expect(screen.getByDisplayValue("console")).toBeDisabled();
    // Each one sits in its own labelled item, so a dropped label is visible.
    expect(screen.getByTestId("label-id")).toHaveTextContent("id");
    expect(screen.getByTestId("label-session_id")).toHaveTextContent(
      "session_id",
    );
    expect(screen.getByTestId("label-user_id")).toHaveTextContent("user_id");
    expect(screen.getByTestId("label-channel")).toHaveTextContent("channel");
  });

  it("renders none of the identity fields when there is no session", () => {
    render(
      <SessionDrawer
        open
        editingSession={null}
        form={makeForm()}
        saving={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("label-session_id")).toBeNull();
    expect(screen.queryByDisplayValue("id-1")).toBeNull();
    // The editable name field stays, since it is not part of the gate.
    expect(screen.getByPlaceholderText("Session name")).toBeInTheDocument();
  });

  it("keeps the name field editable while the identity fields stay locked", () => {
    render(
      <SessionDrawer
        open
        editingSession={SESSION}
        form={makeForm()}
        saving={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByPlaceholderText("Session name")).toBeEnabled();
    expect(screen.getByDisplayValue("id-1")).toBeDisabled();
  });
});

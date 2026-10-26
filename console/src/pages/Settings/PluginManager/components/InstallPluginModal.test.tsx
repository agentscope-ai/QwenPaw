// @vitest-environment jsdom
/**
 * InstallPluginModal tests - the "install a plugin" dialog of the Plugin
 * Manager settings page.
 *
 * The component is purely presentational: every piece of state and every
 * handler arrives through props typed as `ReturnType<typeof useInstallModal>`
 * (minus `openModal`). So the contract under test is the prop -> UI wiring,
 * which is exactly where this dialog has failed before (a handler wired to the
 * wrong element still renders fine).
 *
 * Visible contract under test:
 *
 *   1. with nothing selected the dialog shows the drop zone and hides the
 *      selection card; the local install button is disabled in that state,
 *      because there is nothing to upload;
 *   2. once a selection exists the two swap: the drop zone is gone, the file or
 *      folder name is shown verbatim, and the local install button becomes
 *      clickable and reports through `handleInstallLocal`;
 *   3. the two selection kinds are told apart by their own icon - a folder
 *      selection renders the folder icon, a zip selection the archive icon - so
 *      a collapsed `kind` check cannot pass both;
 *   4. the clear button on the selection card reports `clearSelection`, which is
 *      the only way back to the drop zone;
 *   5. `dragOver` alone switches the drop zone into its highlighted state, and
 *      the three drag handlers are each reported separately (over / leave /
 *      drop), because the hook behind them keeps `dragOver` and the drop payload
 *      apart;
 *   6. clicking the drop zone reports `browseZip` - the mouse-only path into the
 *      same file picker that drag and drop feeds;
 *   7. the hidden file input is a real `input[type=file]` restricted to `.zip`
 *      and forwards its change event to `handleZipPicked`;
 *   8. while an install is in flight the matching button says "installing"
 *      instead of its idle label, and the two flags are independent: local
 *      installing does not relabel the URL button and vice versa;
 *   9. the URL path has two entry points that both report `handleInstallUrl` -
 *      the button click and pressing Enter inside the URL field;
 *  10. closing the dialog reports `closeModal`, and the dialog asks for every
 *      i18n key the product names (pinned as keys, not as rewordable English).
 *
 * Harness notes (measured facts):
 *
 * - The component imports from `antd` (no `@agentscope-ai/design`), so the
 *   shared `src/test/design-mock.ts` is untouched and not needed here.
 * - antd's `Modal` only renders children after its open animation, which never
 *   runs in jsdom, so `Modal` is replaced by a stub that renders title and
 *   children synchronously while `open` is true and reports `onCancel`. The
 *   rest of `antd` is the real module (`vi.importActual`), so `Input`,
 *   `Button`, `Typography`, `Divider` and `Space` behave as shipped -
 *   including `Input`'s `onPressEnter`.
 * - `Form` is stubbed to a plain container because the real one requires a
 *   `FormInstance`; this component only passes `form` through to it and owns no
 *   field logic of its own (that lives in `useInstallModal`).
 * - `lucide-react` is left real, as sibling suites in this directory do, so the
 *   two selection icons are identified by the class the real library emits.
 * - Class names come from the real CSS module import rather than being typed
 *   out, so a renamed style cannot silently pass.
 */
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LocalSelection } from "../utils";
import styles from "./InstallPluginModal.module.less";

const mocks = vi.hoisted(() => ({
  closeModal: vi.fn(),
  clearSelection: vi.fn(),
  browseZip: vi.fn(),
  handleZipPicked: vi.fn(),
  handleDragOver: vi.fn(),
  handleDragLeave: vi.fn(),
  handleDrop: vi.fn(),
  handleInstallLocal: vi.fn(),
  handleInstallUrl: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("antd", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("antd");
  const ReactModule = await import("react");
  const ModalStub = ({
    open,
    title,
    children,
    onCancel,
  }: {
    open?: boolean;
    title?: React.ReactNode;
    children?: React.ReactNode;
    onCancel?: () => void;
  }) => {
    if (!open) return null;
    return ReactModule.createElement(
      "div",
      { "data-testid": "install-modal" },
      ReactModule.createElement(
        "div",
        { "data-testid": "install-modal-title" },
        title,
      ),
      ReactModule.createElement("button", {
        type: "button",
        "aria-label": "close-dialog",
        onClick: onCancel,
      }),
      children,
    );
  };
  const Container = ({ children }: { children?: React.ReactNode }) =>
    ReactModule.createElement("div", null, children);
  const FormStub = Object.assign(Container, { Item: Container });
  return { ...actual, Modal: ModalStub, Form: FormStub };
});

import { InstallPluginModal } from "./InstallPluginModal";

/** The 16 props the component takes, with every handler spied on. */
function makeProps(
  overrides: Partial<Parameters<typeof InstallPluginModal>[0]> = {},
) {
  return {
    installOpen: true,
    closeModal: mocks.closeModal,
    localInstalling: false,
    urlInstalling: false,
    localSel: null as LocalSelection | null,
    clearSelection: mocks.clearSelection,
    dragOver: false,
    form: {} as never,
    fileInputRef: { current: null } as never,
    browseZip: mocks.browseZip,
    handleZipPicked: mocks.handleZipPicked,
    handleDragOver: mocks.handleDragOver,
    handleDragLeave: mocks.handleDragLeave,
    handleDrop: mocks.handleDrop,
    handleInstallLocal: mocks.handleInstallLocal,
    handleInstallUrl: mocks.handleInstallUrl,
    ...overrides,
  };
}

function renderModal(
  overrides: Partial<Parameters<typeof InstallPluginModal>[0]> = {},
) {
  const props = makeProps(overrides);
  const view = render(<InstallPluginModal {...props} />);
  return { ...view, props };
}

const zipSelection: LocalSelection = {
  kind: "zip",
  name: "my-plugin.zip",
  file: new File(["x"], "my-plugin.zip", { type: "application/zip" }),
};

const folderSelection: LocalSelection = {
  kind: "folder",
  name: "my-plugin",
  entries: [
    {
      path: "manifest.json",
      file: new File(["{}"], "manifest.json", { type: "application/json" }),
    },
  ],
};

/**
 * The local install button, found by the i18n key it asks for.
 *
 * The match is a substring one on purpose: while `loading` is set, antd puts
 * its spinner icon in front of the label, so the accessible name becomes
 * `loadingpluginManager.installing` rather than the bare key (measured DOM).
 */
function localInstallButton() {
  return screen.getByRole("button", {
    name: /pluginManager\.installBtn|pluginManager\.installing/,
  });
}

describe("InstallPluginModal", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((fn) => fn.mockClear());
  });

  afterEach(() => {
    // These cases unmount mid-suite (to compare two prop sets), so hand the
    // document back through the library's own cleanup: removing nodes by hand
    // fights the automatic cleanup and throws NotFoundError.
    cleanup();
  });

  it("renders nothing while the dialog is closed", () => {
    renderModal({ installOpen: false });

    expect(screen.queryByTestId("install-modal")).toBeNull();
  });

  it("shows the drop zone and disables local install when nothing is selected", () => {
    renderModal();

    expect(screen.getByText("pluginManager.dropPrimary")).toBeInTheDocument();
    expect(screen.getByText("pluginManager.dropSecondary")).toBeInTheDocument();
    expect(screen.queryByText("my-plugin.zip")).toBeNull();
    expect(localInstallButton()).toBeDisabled();
  });

  it("swaps to the selection card and enables local install once selected", () => {
    renderModal({ localSel: zipSelection });

    expect(screen.getByText("my-plugin.zip")).toBeInTheDocument();
    expect(screen.queryByText("pluginManager.dropPrimary")).toBeNull();

    const button = localInstallButton();
    expect(button).toBeEnabled();

    fireEvent.click(button);
    expect(mocks.handleInstallLocal).toHaveBeenCalledTimes(1);
  });

  it("tells a folder selection from a zip selection by its own icon", () => {
    const folder = renderModal({ localSel: folderSelection });
    const folderIcons = folder.container.querySelectorAll(
      "svg.lucide-folder-open",
    );
    expect(folderIcons.length).toBeGreaterThan(0);
    expect(
      folder.container.querySelectorAll("svg.lucide-file-archive").length,
    ).toBe(0);
    folder.unmount();

    const zip = renderModal({ localSel: zipSelection });
    expect(
      zip.container.querySelectorAll("svg.lucide-file-archive").length,
    ).toBeGreaterThan(0);
  });

  it("reports clearSelection from the button on the selection card", () => {
    const { container } = renderModal({ localSel: zipSelection });

    const card = container.querySelector(`.${styles.selectionCard}`);
    expect(card).not.toBeNull();

    const clearButton = within(card as HTMLElement).getByRole("button");
    fireEvent.click(clearButton);

    expect(mocks.clearSelection).toHaveBeenCalledTimes(1);
  });

  it("highlights the drop zone only while dragOver is set", () => {
    const idle = renderModal();
    const idleZone = idle.container.querySelector(`.${styles.dropZone}`);
    expect(idleZone).not.toBeNull();
    expect(idleZone?.className).not.toContain(styles.dropZoneActive);
    idle.unmount();

    const dragging = renderModal({ dragOver: true });
    const draggingZone = dragging.container.querySelector(
      `.${styles.dropZone}`,
    );
    expect(draggingZone?.className).toContain(styles.dropZoneActive);
  });

  it("reports each of the three drag handlers separately", () => {
    const { container } = renderModal();
    const zone = container.querySelector(`.${styles.dropZone}`) as HTMLElement;
    expect(zone).not.toBeNull();

    fireEvent.dragOver(zone);
    expect(mocks.handleDragOver).toHaveBeenCalledTimes(1);
    expect(mocks.handleDragLeave).not.toHaveBeenCalled();
    expect(mocks.handleDrop).not.toHaveBeenCalled();

    fireEvent.dragLeave(zone);
    expect(mocks.handleDragLeave).toHaveBeenCalledTimes(1);
    expect(mocks.handleDrop).not.toHaveBeenCalled();

    fireEvent.drop(zone);
    expect(mocks.handleDrop).toHaveBeenCalledTimes(1);
  });

  it("reports browseZip when the drop zone is clicked", () => {
    const { container } = renderModal();
    const zone = container.querySelector(`.${styles.dropZone}`) as HTMLElement;

    fireEvent.click(zone);

    expect(mocks.browseZip).toHaveBeenCalledTimes(1);
  });

  it("renders a hidden zip-only file input wired to handleZipPicked", () => {
    const { container } = renderModal();

    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    expect(input?.getAttribute("accept")).toBe(".zip");
    expect((input as HTMLInputElement).style.display).toBe("none");

    fireEvent.change(input as HTMLInputElement);
    expect(mocks.handleZipPicked).toHaveBeenCalledTimes(1);
  });

  it("relabels only the button whose install is in flight", () => {
    const local = renderModal({
      localSel: zipSelection,
      localInstalling: true,
    });
    // While loading, antd prefixes the accessible name with its spinner label.
    expect(
      screen.getByRole("button", { name: /pluginManager\.installing/ }),
    ).toBeInTheDocument();
    // The URL button keeps its idle label while the local upload runs.
    expect(
      screen.getByRole("button", { name: "pluginManager.installFromUrl" }),
    ).toBeInTheDocument();
    local.unmount();

    renderModal({ urlInstalling: true });
    expect(
      screen.getByRole("button", { name: /pluginManager\.installing/ }),
    ).toBeInTheDocument();
    // The local button is back to its idle label and is disabled (no selection).
    expect(
      screen.getByRole("button", { name: "pluginManager.installBtn" }),
    ).toBeInTheDocument();
  });

  it("reports handleInstallUrl from both the button and the Enter key", () => {
    renderModal();

    fireEvent.click(
      screen.getByRole("button", { name: "pluginManager.installFromUrl" }),
    );
    expect(mocks.handleInstallUrl).toHaveBeenCalledTimes(1);

    const urlInput = screen.getByPlaceholderText(
      "pluginManager.urlPlaceholder",
    );
    fireEvent.keyDown(urlInput, { key: "Enter", code: "Enter" });
    expect(mocks.handleInstallUrl).toHaveBeenCalledTimes(2);
  });

  it("reports closeModal when the dialog is dismissed", () => {
    renderModal();

    fireEvent.click(screen.getByLabelText("close-dialog"));

    expect(mocks.closeModal).toHaveBeenCalledTimes(1);
  });

  it("asks for every i18n key the dialog names", () => {
    renderModal({ localSel: zipSelection });

    // The idle labels: `installing` replaces `installBtn` only while a flag
    // is set, and `dropPrimary`/`dropSecondary` only while nothing is
    // selected, so this case (a selection, no install in flight) pins these.
    [
      "pluginManager.installTitle",
      "pluginManager.installBtn",
      "pluginManager.orFromUrl",
      "pluginManager.installFromUrl",
      "pluginManager.restartHint",
    ].forEach((key) => {
      expect(screen.getByText(key)).toBeInTheDocument();
    });

    // This one is asked for as an attribute, not as text, so it is looked up
    // the way it is rendered rather than through getByText.
    expect(
      screen.getByPlaceholderText("pluginManager.urlPlaceholder"),
    ).toBeInTheDocument();
  });
});

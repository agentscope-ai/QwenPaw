/**
 * FilesPage - the routed agent workspace page (pages/Files/index.tsx). It is
 * lazy-loaded from layouts/registry/builtinRoutes.tsx:52, so this render is the
 * only unit-level look at it.
 *
 * What this file pins:
 *   1. the page hands FilesWorkspace an "agent" scope built from the store's
 *      selectedAgent. The shape is a contract, not a detail: FilesWorkspace
 *      branches on scope.kind and on scope.agentId, and a session scope would
 *      make it resolve a chat/project directory instead. Asserted as a whole
 *      object so an extra key (or a renamed one) fails here;
 *   2. the scope follows the store: a different selectedAgent produces a
 *      different agentId, so the page cannot be pinned to one agent;
 *   3. the accessible name and the heading come from the two i18n keys the
 *      product itself asks for (files.agentWorkspace on the section's
 *      aria-label, files.title in the <strong>); both are present in
 *      src/locales/en.json as "Agent workspace" and "Files";
 *   4. the icon slot is decorative: the wrapping div carries aria-hidden="true"
 *      and the lucide icon is sized 17, so screen readers get the heading and
 *      not the glyph;
 *   5. the structural class names from the two stylesheets stay on the right
 *      elements (page/workspace from this page's module, drawerHeader/fileMark/
 *      drawerTitle borrowed from the files-workspace module) - these are the
 *      hooks a browser-level test would have to use;
 *   6. the workspace slot wraps exactly one FilesWorkspace, so the page cannot
 *      silently render two workspaces or none.
 *
 * FilesWorkspace is replaced with a prop-capture stub (same shape as the
 * @ant-design/plots stub already used in TokenUsage/index.test.tsx) because the
 * real one pulls in the file API, coding-mode store and preview pipeline; it
 * has its own coverage. The stub re-publishes the received props as data-*
 * attributes so assertions read the DOM rather than the stub's internals.
 * The agent store is stubbed to keep selectedAgent under test control.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

import FilesPage from "./index";
import styles from "./index.module.less";
import workspaceStyles from "../../features/files-workspace/FilesWorkspace.module.less";

const storeState = vi.hoisted(() => ({ selectedAgent: "agent-alpha" }));
const capturedScopes = vi.hoisted(() => [] as unknown[]);

vi.mock("../../features/files-workspace/FilesWorkspace", () => ({
  default: (props: { scope: unknown; initialTarget?: unknown }) => {
    capturedScopes.push(props.scope);
    return (
      <div
        data-stub="files-workspace"
        data-scope={JSON.stringify(props.scope)}
        data-has-initial-target={String("initialTarget" in props)}
        data-prop-count={String(Object.keys(props).length)}
      />
    );
  },
}));

vi.mock("../../stores/agentStore", () => ({
  useAgentStore: () => ({ selectedAgent: storeState.selectedAgent }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
}));

function scopeFrom(dom: HTMLElement): Record<string, unknown> {
  const stub = dom.querySelector("[data-stub=files-workspace]");
  expect(stub).not.toBeNull();
  const raw = stub!.getAttribute("data-scope");
  expect(typeof raw).toBe("string");
  expect(raw!.length).toBeGreaterThan(0);
  return JSON.parse(raw!) as Record<string, unknown>;
}

describe("FilesPage workspace scope", () => {
  beforeEach(() => {
    storeState.selectedAgent = "agent-alpha";
    capturedScopes.length = 0;
  });

  it("hands FilesWorkspace an agent scope carrying the selected agent", () => {
    const { container } = render(<FilesPage />);
    expect(scopeFrom(container)).toEqual({
      kind: "agent",
      agentId: "agent-alpha",
    });
  });

  it("builds the scope with exactly those two keys", () => {
    render(<FilesPage />);
    // A whole-object assertion above cannot see a key added later; this one can.
    expect(capturedScopes[0]).toBeDefined();
    expect(Object.keys(capturedScopes[0] as object).sort()).toEqual([
      "agentId",
      "kind",
    ]);
  });

  it("follows the store's selectedAgent", () => {
    storeState.selectedAgent = "agent-beta";
    const { container } = render(<FilesPage />);
    expect(scopeFrom(container).agentId).toBe("agent-beta");
    expect(scopeFrom(container).kind).toBe("agent");
  });

  it("passes an empty agent id through unchanged rather than inventing one", () => {
    storeState.selectedAgent = "";
    const { container } = render(<FilesPage />);
    expect(scopeFrom(container)).toEqual({ kind: "agent", agentId: "" });
  });

  it("does not supply an initialTarget", () => {
    const { container } = render(<FilesPage />);
    const stub = container.querySelector("[data-stub=files-workspace]");
    expect(stub?.getAttribute("data-has-initial-target")).toBe("false");
    expect(stub?.getAttribute("data-prop-count")).toBe("1");
  });
});

describe("FilesPage labels and structure", () => {
  beforeEach(() => {
    storeState.selectedAgent = "agent-alpha";
    capturedScopes.length = 0;
  });

  it("names the section with the workspace i18n key", () => {
    const { container } = render(<FilesPage />);
    const section = container.querySelector("section");
    expect(section).not.toBeNull();
    expect(section?.getAttribute("aria-label")).toBe("files.agentWorkspace");
  });

  it("puts the title key in the heading", () => {
    const { container } = render(<FilesPage />);
    const heading = container.querySelector("header strong");
    expect(heading?.textContent).toBe("files.title");
  });

  it("marks the icon slot as decorative", () => {
    const { container } = render(<FilesPage />);
    const mark = container.querySelector("header [aria-hidden]");
    expect(mark?.getAttribute("aria-hidden")).toBe("true");
    expect(mark?.className).toContain(workspaceStyles.fileMark);
    // The lucide icon renders as a real <svg> sized by the size prop.
    const svg = mark?.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("width")).toBe("17");
    expect(svg?.getAttribute("height")).toBe("17");
  });

  it("keeps the structural class names on the right elements", () => {
    const { container } = render(<FilesPage />);
    // Module class names are generated; assert they resolve before comparing.
    expect(styles.page.length).toBeGreaterThan(0);
    expect(styles.workspace.length).toBeGreaterThan(0);
    expect(workspaceStyles.drawerHeader.length).toBeGreaterThan(0);
    expect(workspaceStyles.drawerTitle.length).toBeGreaterThan(0);
    expect(container.querySelector("section")?.className).toBe(styles.page);
    expect(container.querySelector("header")?.className).toBe(
      workspaceStyles.drawerHeader,
    );
    expect(container.querySelector("header > div:last-child")?.className).toBe(
      workspaceStyles.drawerTitle,
    );
    expect(container.querySelector("section > div")?.className).toBe(
      styles.workspace,
    );
  });

  it("wraps exactly one workspace in the slot", () => {
    const { container } = render(<FilesPage />);
    const slot = container.querySelector(`div.${styles.workspace}`);
    expect(slot).not.toBeNull();
    expect(slot?.querySelectorAll("[data-stub=files-workspace]")).toHaveLength(
      1,
    );
    expect(
      container.querySelectorAll("[data-stub=files-workspace]"),
    ).toHaveLength(1);
  });

  it("renders one header and one section, with the header inside the section", () => {
    const { container } = render(<FilesPage />);
    expect(container.querySelectorAll("section")).toHaveLength(1);
    expect(container.querySelectorAll("header")).toHaveLength(1);
    expect(
      container
        .querySelector("section")
        ?.contains(container.querySelector("header")!),
    ).toBe(true);
  });
});

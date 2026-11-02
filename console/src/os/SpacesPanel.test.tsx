/**
 * SpacesPanel — top-edge Space (agent) switcher.
 *
 * The panel is a thin projection of two stores: which agents are chat-visible
 * (agentStore) and which Space is currently open (osWindowStore). Both stores
 * are driven for real here, so these cases pin the observable contract a user
 * relies on: the chip list, which chip is marked active, what a click does,
 * and the keyboard/pointer affordances inherited from buttonRoleProps.
 *
 * antd-style hashes every class combination into a single token, so styling
 * cases compare hash values rather than counting tokens or matching literal
 * generated names.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { useAgentStore } from "../stores/agentStore";
import { useOsWindows } from "./osWindowStore";
import SpacesPanel from "./SpacesPanel";

interface AgentFixture {
  available_in_chat?: boolean;
}

/** Build a full AgentSummary from the few fields a case actually cares about. */
function agent(id: string, name: string, extra: AgentFixture = {}): never {
  return {
    id,
    name,
    description: "",
    workspace_dir: "",
    enabled: true,
    backend: "qwenpaw",
    ...extra,
  } as never;
}

/** Tokens in the class list of an element. */
function tokens(el: Element): string[] {
  return el.className.split(" ").filter(Boolean);
}

/**
 * The panel's own root element. renderWithProviders wraps the tree in antd's
 * App provider, so container.firstElementChild is that wrapper — the panel
 * root is the element that holds the chips.
 */
function panelRoot(container: HTMLElement): Element {
  const el = container.querySelector('[role="button"]')?.parentElement;
  if (!el) throw new Error("panel root not found");
  return el;
}

beforeEach(() => {
  vi.clearAllMocks();
  useAgentStore.setState({
    selectedAgent: "alpha",
    agents: [agent("alpha", "Alpha"), agent("beta", "Beta")],
  });
  useOsWindows.setState({
    activeId: null,
    spaceId: "alpha",
    missionControlOpen: false,
    saved: {},
  });
});

describe("SpacesPanel chip list", () => {
  it("renders one chip per chat-visible agent, in store order", () => {
    renderWithProviders(<SpacesPanel visible />);

    const chips = screen.getAllByRole("button");
    expect(chips).toHaveLength(2);
    expect(chips.map((c) => c.getAttribute("aria-label"))).toEqual([
      "Alpha",
      "Beta",
    ]);
  });

  it("renders a bare panel when the only agent is unavailable to chat", () => {
    // The fallback branch unshifts the selection unless that agent record
    // exists and is explicitly unavailable — the one way to reach zero chips.
    useAgentStore.setState({
      selectedAgent: "ghost",
      agents: [agent("ghost", "Ghost", { available_in_chat: false })],
    });
    const { container } = renderWithProviders(<SpacesPanel visible />);

    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(container).toBeInTheDocument();
  });

  it("drops agents whose available_in_chat is false", () => {
    useAgentStore.setState({
      selectedAgent: "alpha",
      agents: [
        agent("alpha", "Alpha"),
        agent("hidden", "Hidden", { available_in_chat: false }),
        agent("beta", "Beta"),
      ],
    });
    renderWithProviders(<SpacesPanel visible />);

    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(screen.queryByText("Hidden")).toBeNull();
  });

  it("keeps agents whose available_in_chat is true or absent", () => {
    useAgentStore.setState({
      selectedAgent: "alpha",
      agents: [
        agent("alpha", "Alpha", { available_in_chat: true }),
        agent("beta", "Beta"),
      ],
    });
    renderWithProviders(<SpacesPanel visible />);

    expect(screen.getAllByRole("button")).toHaveLength(2);
  });

  it("shows the agent name as the chip label", () => {
    renderWithProviders(<SpacesPanel visible />);

    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("falls back to the id for both label and initial when the name is empty", () => {
    useAgentStore.setState({
      selectedAgent: "alpha",
      agents: [agent("zed", "")],
    });
    renderWithProviders(<SpacesPanel visible />);

    const chip = screen.getByRole("button", { name: "zed" });
    expect(chip).toBeInTheDocument();
    // initial = (name || id).charAt(0).toUpperCase()
    expect(within(chip).getByText("Z")).toBeInTheDocument();
    // The name div renders the raw (empty) name, so there is no text node.
    expect(within(chip).queryByText("zed")).toBeNull();
  });

  it("uppercases only the first character of the initial", () => {
    useAgentStore.setState({
      selectedAgent: "alpha",
      agents: [agent("alpha", "lowercase name")],
    });
    renderWithProviders(<SpacesPanel visible />);

    expect(screen.getByText("L")).toBeInTheDocument();
    expect(screen.queryByText("l")).toBeNull();
  });
});

describe("SpacesPanel selected-agent fallback", () => {
  it("labels a chat-visible selection by name rather than prepending its id", () => {
    useAgentStore.setState({
      selectedAgent: "gamma",
      agents: [
        agent("gamma", "Gamma", { available_in_chat: true }),
        agent("hidden", "Hidden", { available_in_chat: false }),
      ],
    });
    renderWithProviders(<SpacesPanel visible />);

    // "gamma" survives the chat-visible filter, so it is already in the list
    // and the fallback branch never runs; the chip keeps the agent's name.
    const chips = screen.getAllByRole("button");
    expect(chips.map((c) => c.getAttribute("aria-label"))).toEqual(["Gamma"]);
  });

  it("prepends the selection when no agent record matches it at all", () => {
    useAgentStore.setState({
      selectedAgent: "orphan",
      agents: [agent("alpha", "Alpha")],
    });
    renderWithProviders(<SpacesPanel visible />);

    const chips = screen.getAllByRole("button");
    expect(chips.map((c) => c.getAttribute("aria-label"))).toEqual([
      "orphan",
      "Alpha",
    ]);
  });

  it("does not prepend a selected agent that is explicitly not chat-visible", () => {
    useAgentStore.setState({
      selectedAgent: "hidden",
      agents: [
        agent("hidden", "Hidden", { available_in_chat: false }),
        agent("alpha", "Alpha"),
      ],
    });
    renderWithProviders(<SpacesPanel visible />);

    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "hidden" })).toBeNull();
    expect(screen.getByRole("button", { name: "Alpha" })).toBeInTheDocument();
  });

  it("does not duplicate the selection when it is already in the list", () => {
    useAgentStore.setState({
      selectedAgent: "beta",
      agents: [agent("alpha", "Alpha"), agent("beta", "Beta")],
    });
    renderWithProviders(<SpacesPanel visible />);

    const chips = screen.getAllByRole("button");
    expect(chips).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Beta" })).toHaveLength(1);
  });
});

describe("SpacesPanel active chip", () => {
  it("marks the chip matching the open space id", () => {
    useOsWindows.setState({ spaceId: "beta" });
    const { container } = renderWithProviders(<SpacesPanel visible />);

    const chips = screen.getAllByRole("button");
    // cx() folds the modifier into one hashed token, so the active chip differs
    // by hash value rather than by carrying an extra token.
    expect(chips[1].className).not.toBe(chips[0].className);
    expect(tokens(chips[0])).toHaveLength(1);
    expect(tokens(chips[1])).toHaveLength(1);
    expect(panelRoot(container).tagName).toBe("DIV");
  });

  it("marks no chip when the open space is not in the list", () => {
    useOsWindows.setState({ spaceId: "nowhere" });
    renderWithProviders(<SpacesPanel visible />);

    const chips = screen.getAllByRole("button");
    // With no active space every chip renders with the identical hash.
    expect(chips[0].className).toBe(chips[1].className);
    expect(tokens(chips[0])).toHaveLength(1);
  });

  it("moves the active mark when the open space changes", () => {
    useOsWindows.setState({ spaceId: "alpha" });
    renderWithProviders(<SpacesPanel visible />);
    const before = screen.getAllByRole("button").map((c) => c.className);
    expect(before[0]).not.toBe(before[1]);

    act(() => {
      useOsWindows.setState({ spaceId: "beta" });
    });
    const after = screen.getAllByRole("button").map((c) => c.className);

    // The two chips exchanged hashes: the mark moved from the first to the
    // second without either chip being recreated with a new style.
    expect(after[0]).toBe(before[1]);
    expect(after[1]).toBe(before[0]);
  });
});

describe("SpacesPanel visibility modifier", () => {
  it("carries a different hash when not visible", () => {
    const shown = renderWithProviders(<SpacesPanel visible />);
    const hidden = renderWithProviders(<SpacesPanel visible={false} />);

    const shownRoot = panelRoot(shown.container);
    const hiddenRoot = panelRoot(hidden.container);

    // The hidden modifier is folded into the same single token, so the
    // observable difference is the hash value, not an extra token.
    expect(tokens(shownRoot)).toHaveLength(1);
    expect(tokens(hiddenRoot)).toHaveLength(1);
    expect(hiddenRoot.className).not.toBe(shownRoot.className);
  });

  it("still renders every chip while hidden", () => {
    renderWithProviders(<SpacesPanel visible={false} />);

    expect(screen.getAllByRole("button")).toHaveLength(2);
  });
});

describe("SpacesPanel activation", () => {
  it("selects the agent and switches the space on click", () => {
    renderWithProviders(<SpacesPanel visible />);

    fireEvent.click(screen.getByRole("button", { name: "Beta" }));

    expect(useAgentStore.getState().selectedAgent).toBe("beta");
    expect(useOsWindows.getState().spaceId).toBe("beta");
  });

  it("activates on the Enter key", () => {
    renderWithProviders(<SpacesPanel visible />);

    fireEvent.keyDown(screen.getByRole("button", { name: "Beta" }), {
      key: "Enter",
    });

    expect(useAgentStore.getState().selectedAgent).toBe("beta");
    expect(useOsWindows.getState().spaceId).toBe("beta");
  });

  it("activates on the space bar", () => {
    renderWithProviders(<SpacesPanel visible />);

    fireEvent.keyDown(screen.getByRole("button", { name: "Beta" }), {
      key: " ",
    });

    expect(useOsWindows.getState().spaceId).toBe("beta");
  });

  it("prevents the default action for both activating keys", () => {
    renderWithProviders(<SpacesPanel visible />);
    const chip = screen.getByRole("button", { name: "Beta" });

    const enter = fireEvent.keyDown(chip, { key: "Enter", cancelable: true });
    const space = fireEvent.keyDown(chip, { key: " ", cancelable: true });

    // fireEvent returns false when preventDefault was called on a cancelable
    // event; both activating keys must suppress the default.
    expect(enter).toBe(false);
    expect(space).toBe(false);
  });

  it("ignores keys that are not Enter or space", () => {
    renderWithProviders(<SpacesPanel visible />);

    fireEvent.keyDown(screen.getByRole("button", { name: "Beta" }), {
      key: "a",
    });
    fireEvent.keyDown(screen.getByRole("button", { name: "Beta" }), {
      key: "Tab",
    });

    expect(useAgentStore.getState().selectedAgent).toBe("alpha");
    expect(useOsWindows.getState().spaceId).toBe("alpha");
  });

  it("does not treat Tab as activating even though it is a focus key", () => {
    renderWithProviders(<SpacesPanel visible />);
    const chip = screen.getByRole("button", { name: "Beta" });

    const tab = fireEvent.keyDown(chip, { key: "Tab", cancelable: true });

    expect(tab).toBe(true);
    expect(useOsWindows.getState().spaceId).toBe("alpha");
  });

  it("exposes every chip as a focusable button", () => {
    renderWithProviders(<SpacesPanel visible />);

    for (const chip of screen.getAllByRole("button")) {
      expect(chip.getAttribute("tabindex")).toBe("0");
    }
  });

  it("re-activating the already-open space keeps the space id stable", () => {
    useOsWindows.setState({ spaceId: "alpha" });
    renderWithProviders(<SpacesPanel visible />);

    fireEvent.click(screen.getByRole("button", { name: "Alpha" }));

    expect(useOsWindows.getState().spaceId).toBe("alpha");
    expect(useAgentStore.getState().selectedAgent).toBe("alpha");
  });
});

describe("SpacesPanel pointer containment", () => {
  it("stops pointerdown from reaching the desktop, with a positive control", () => {
    const parent = vi.fn();
    renderWithProviders(
      <div onPointerDown={parent}>
        <SpacesPanel visible />
        <div data-testid="outside">outside</div>
      </div>,
    );

    // Positive control: an element outside the panel does reach the desktop.
    fireEvent.pointerDown(screen.getByTestId("outside"));
    expect(parent).toHaveBeenCalledTimes(1);

    // The panel swallows it, so the desktop never hides the panel.
    fireEvent.pointerDown(screen.getByRole("button", { name: "Alpha" }));
    fireEvent.pointerDown(screen.getByRole("button", { name: "Beta" }));
    expect(parent).toHaveBeenCalledTimes(1);
  });

  it("keeps swallowing pointerdown while hidden", () => {
    const parent = vi.fn();
    renderWithProviders(
      <div onPointerDown={parent}>
        <SpacesPanel visible={false} />
      </div>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: "Alpha" }));

    expect(parent).not.toHaveBeenCalled();
  });
});

describe("SpacesPanel chip colour", () => {
  // jsdom normalises the inline hex values to rgb() triplets, so the palette is
  // pinned in the form the DOM actually reports.
  const PALETTE_RGB = [
    "rgb(255, 127, 22)",
    "rgb(59, 130, 246)",
    "rgb(139, 92, 246)",
    "rgb(16, 185, 129)",
    "rgb(236, 72, 153)",
    "rgb(6, 182, 212)",
    "rgb(245, 158, 11)",
  ];

  function avatarColours(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll(".avatar"))
      .filter((el): el is HTMLElement => el instanceof HTMLElement)
      .map((el) => el.style.background);
  }

  it("gives every chip a colour from the fixed palette", () => {
    useAgentStore.setState({
      selectedAgent: "alpha",
      agents: ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"].map((id) =>
        agent(id, id),
      ),
    });
    const { container } = renderWithProviders(<SpacesPanel visible />);

    const colours = avatarColours(container);
    expect(colours).toHaveLength(6);
    for (const colour of colours) {
      expect(PALETTE_RGB).toContain(colour);
    }
  });

  it("is deterministic: the same id renders the same colour twice", () => {
    const first = renderWithProviders(<SpacesPanel visible />);
    const second = renderWithProviders(<SpacesPanel visible />);

    const firstColours = avatarColours(first.container);
    const secondColours = avatarColours(second.container);

    expect(firstColours).toHaveLength(2);
    expect(secondColours).toEqual(firstColours);
  });

  it("pins the id-to-colour mapping, including ids that collide", () => {
    useAgentStore.setState({
      selectedAgent: "alpha",
      agents: ["alpha", "beta", "gamma", "zeta"].map((id) => agent(id, id)),
    });
    const { container } = renderWithProviders(<SpacesPanel visible />);

    // "alpha" and "beta" hash into the same slot, so a collision is the
    // current designed behaviour rather than a unique-colour guarantee.
    expect(avatarColours(container)).toEqual([
      "rgb(16, 185, 129)",
      "rgb(16, 185, 129)",
      "rgb(6, 182, 212)",
      "rgb(255, 127, 22)",
    ]);
  });

  it("does not reuse one colour for every chip", () => {
    useAgentStore.setState({
      selectedAgent: "alpha",
      agents: ["alpha", "gamma", "delta", "epsilon", "zeta", "theta"].map(
        (id) => agent(id, id),
      ),
    });
    const { container } = renderWithProviders(<SpacesPanel visible />);

    const colours = avatarColours(container);
    expect(new Set(colours).size).toBe(6);
  });
});

describe("SpacesPanel store subscription", () => {
  it("re-renders when an agent is added to the store", () => {
    renderWithProviders(<SpacesPanel visible />);
    expect(screen.getAllByRole("button")).toHaveLength(2);

    act(() => {
      useAgentStore.setState({
        agents: [
          agent("alpha", "Alpha"),
          agent("beta", "Beta"),
          agent("gamma", "Gamma"),
        ],
      });
    });

    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Gamma" })).toBeInTheDocument();
  });

  it("re-renders when an agent is removed", () => {
    renderWithProviders(<SpacesPanel visible />);

    act(() => {
      useAgentStore.setState({ agents: [agent("alpha", "Alpha")] });
    });

    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Beta" })).toBeNull();
  });
});

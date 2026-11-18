/**
 * MissionControl - macOS style Spaces switcher overlay.
 *
 * The overlay is a thin projection of two stores: which agents are chat
 * visible (agentStore) and which windows belong to the current space
 * (osWindowStore). Both stores are driven for real here, so these cases pin
 * the contract a user relies on: which spaces are listed, what each card
 * shows, what selecting a space does, how the open window grid resolves app
 * metadata, and every path that dismisses the overlay.
 *
 * Notes on this harness:
 * 1. `src/test/setup.ts` does not initialise i18next, so `t(key, fallback)`
 *    returns the fallback string. Assertions use those English fallbacks,
 *    which is also what a user sees before translations have loaded.
 * 2. antd-style hashes every class combination into one opaque token: a card
 *    that is both `mcSpaceCard` and `mcSpaceActive` carries a single merged
 *    hash, not two classes. The highlight cases therefore compare token
 *    *values* across renders rather than counting tokens or matching names.
 * 3. Unknown route ids are exercised through the component's own
 *    `?? OS_APPS[0]` guard, so the real app registry stays in play and no
 *    module is mocked away.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { useAgentStore } from "../stores/agentStore";
import { useOsWindows, type OsWindow } from "./osWindowStore";
import type { AgentSummary } from "../api/types/agents";
import MissionControl from "./MissionControl";

/** The seven space colours the component documents, in jsdom's rgb() form. */
const PALETTE_RGB = [
  "rgb(255, 127, 22)",
  "rgb(59, 130, 246)",
  "rgb(139, 92, 246)",
  "rgb(16, 185, 129)",
  "rgb(236, 72, 153)",
  "rgb(6, 182, 212)",
  "rgb(245, 158, 11)",
];

/** Build a full AgentSummary from the few fields a case actually cares about. */
function agent(
  id: string,
  name: string,
  extra: Partial<AgentSummary> = {},
): AgentSummary {
  return {
    id,
    name,
    description: "",
    workspace_dir: "",
    enabled: true,
    backend: "qwenpaw",
    ...extra,
  };
}

/** A window record; geometry is irrelevant to this overlay but required. */
function win(id: string, extra: Partial<OsWindow> = {}): OsWindow {
  return {
    id,
    x: 40,
    y: 60,
    w: 800,
    h: 500,
    z: 10,
    minimized: false,
    maximized: false,
    ...extra,
  };
}

/** A saved (inactive) space snapshot. */
function savedSpace(order: string[]): never {
  return { windows: {}, order, activeId: null, zCounter: 10 } as never;
}

/** Class tokens of an element. */
function tokens(el: Element): string[] {
  return el.className.split(" ").filter(Boolean);
}

/**
 * aria-labels of every clickable element, in DOM order.
 *
 * Uses the role *query* rather than an attribute selector: the close control
 * is a native <button>, whose button role is implicit and therefore invisible
 * to `[role="button"]`.
 */
function clickableLabels(): (string | null)[] {
  return screen
    .queryAllByRole("button")
    .map((el) => el.getAttribute("aria-label"));
}

/**
 * One of the overlay's two sections, by position.
 *
 * The overlay is a dialog whose children are the spaces row, the window grid
 * and the close button, in that order. Both rows swallow clicks so that only
 * the backdrop dismisses the overlay, and neither carries a role of its own,
 * so the section under test is addressed by position.
 */
function sectionRow(index: number): HTMLElement {
  const row = screen.getByRole("dialog").children[index];
  if (!row) throw new Error(`overlay section ${index} not found`);
  return row as HTMLElement;
}

/** The row that holds the space cards. */
function spacesRow(): HTMLElement {
  return sectionRow(0);
}

/** The row that holds the current space's window cards. */
function windowsRow(): HTMLElement {
  return sectionRow(1);
}

/** Icons rendered inside the window grid (excludes the close control). */
function windowGridIcons(): number {
  return windowsRow().querySelectorAll("svg").length;
}

/** The avatar backgrounds currently rendered, in DOM order. */
function avatarColors(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll(".avatar")).map(
    (el) => (el as HTMLElement).style.background,
  );
}

/** Put the stores into a known two agent / empty desktop state. */
function resetStores(): void {
  useAgentStore.setState({
    selectedAgent: "alpha",
    agents: [agent("alpha", "Alpha"), agent("beta", "Beta")],
  });
  useOsWindows.setState({
    spaceId: "alpha",
    saved: {},
    windows: {},
    order: [],
    activeId: null,
    zCounter: 100,
    launcherOpen: false,
    missionControlOpen: true,
  });
}

beforeEach(() => {
  resetStores();
});

describe("Mission Control dialog contract", () => {
  it("is exposed as a modal dialog with an accessible name", () => {
    renderWithProviders(<MissionControl />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-label", "Mission Control");
  });

  it("always offers a close control labelled for screen readers", () => {
    renderWithProviders(<MissionControl />);

    const close = screen.getByRole("button", { name: "Close" });
    expect(close).toHaveAttribute("title", "Close");
    expect(close.tagName).toBe("BUTTON");
  });

  it("renders both sections even with no agents and no windows", () => {
    useAgentStore.setState({ selectedAgent: "alpha", agents: [] });
    renderWithProviders(<MissionControl />);

    // The fallback branch still lists the selected agent as a space, so the
    // overlay is never an empty rectangle.
    expect(clickableLabels()).toEqual(["alpha", "Close"]);
    expect(
      screen.getByText("No open windows in this space"),
    ).toBeInTheDocument();
  });
});

describe("space list projection", () => {
  it("lists one card per chat visible agent, in store order", () => {
    const { container } = renderWithProviders(<MissionControl />);

    expect(
      screen
        .getAllByRole("button")
        .slice(0, 2)
        .map((b) => b.getAttribute("aria-label")),
    ).toEqual(["Alpha", "Beta"]);
    expect(
      Array.from(container.querySelectorAll(".name")).map((n) => n.textContent),
    ).toEqual(["Alpha", "Beta"]);
  });

  it("drops agents that are unavailable in chat", () => {
    useAgentStore.setState({
      selectedAgent: "alpha",
      agents: [
        agent("alpha", "Alpha"),
        agent("hidden", "Hidden", { available_in_chat: false }),
        agent("beta", "Beta"),
      ],
    });
    renderWithProviders(<MissionControl />);

    expect(clickableLabels()).toEqual(["Alpha", "Beta", "Close"]);
    expect(screen.queryByText("Hidden")).toBeNull();
  });

  it("keeps agents whose available_in_chat is explicitly true", () => {
    useAgentStore.setState({
      selectedAgent: "alpha",
      agents: [agent("alpha", "Alpha", { available_in_chat: true })],
    });
    renderWithProviders(<MissionControl />);

    expect(clickableLabels()).toEqual(["Alpha", "Close"]);
  });

  it("prepends the selected agent when it is not in the loaded list yet", () => {
    // The agent list arrives from the backend after boot, so the current
    // agent must still have a space to sit in.
    useAgentStore.setState({
      selectedAgent: "nobody",
      agents: [agent("alpha", "Alpha")],
    });
    const { container } = renderWithProviders(<MissionControl />);

    expect(clickableLabels()).toEqual(["nobody", "Alpha", "Close"]);
    // With no agent record there is no display name, so the id doubles as one.
    expect(
      Array.from(container.querySelectorAll(".name")).map((n) => n.textContent),
    ).toEqual(["nobody", "Alpha"]);
    expect(
      Array.from(container.querySelectorAll(".avatar")).map(
        (a) => a.textContent,
      ),
    ).toEqual(["N", "A"]);
  });

  it("does not prepend an agent that is explicitly unavailable in chat", () => {
    // The one way to reach an overlay with zero space cards: the selection is
    // an app owned profile that must not appear in Chat.
    useAgentStore.setState({
      selectedAgent: "ghost",
      agents: [agent("ghost", "Ghost", { available_in_chat: false })],
    });
    renderWithProviders(<MissionControl />);

    expect(clickableLabels()).toEqual(["Close"]);
    expect(screen.queryByText("Ghost")).toBeNull();
  });

  it("does not duplicate the selection when it is already listed", () => {
    useAgentStore.setState({
      selectedAgent: "beta",
      agents: [agent("alpha", "Alpha"), agent("beta", "Beta")],
    });
    renderWithProviders(<MissionControl />);

    expect(clickableLabels()).toEqual(["Alpha", "Beta", "Close"]);
  });

  it("falls back to the id for the initial when an agent has no name", () => {
    useAgentStore.setState({
      selectedAgent: "blank",
      agents: [agent("blank", ""), agent("alpha", "Alpha")],
    });
    const { container } = renderWithProviders(<MissionControl />);

    expect(
      Array.from(container.querySelectorAll(".avatar")).map(
        (a) => a.textContent,
      ),
    ).toEqual(["B", "A"]);
    // The name row stays empty rather than showing the id a second time.
    expect(
      Array.from(container.querySelectorAll(".name")).map((n) => n.textContent),
    ).toEqual(["", "Alpha"]);
  });
});

describe("space avatar colour", () => {
  it("gives the same agent the same colour on every render", () => {
    const first = renderWithProviders(<MissionControl />);
    const before = avatarColors(first.container);
    first.unmount();

    const second = renderWithProviders(<MissionControl />);
    expect(avatarColors(second.container)).toEqual(before);
    expect(before.length).toBe(2);
  });

  it("picks a colour from the documented palette for every agent", () => {
    useAgentStore.setState({
      selectedAgent: "a",
      agents: [
        agent("a", "A"),
        agent("b", "B"),
        agent("gamma", "Gamma"),
        agent("delta", "Delta"),
        agent("epsilon", "Epsilon"),
      ],
    });
    const { container } = renderWithProviders(<MissionControl />);

    const colors = avatarColors(container);
    expect(colors).toHaveLength(5);
    colors.forEach((c) => expect(PALETTE_RGB).toContain(c));
  });

  it("still yields a palette colour when the id hashes negative", () => {
    // Long ids overflow into negative int32 hashes; without an absolute value
    // the modulo would index outside the palette and the avatar would lose its
    // background entirely.
    const longId = "agent-with-a-very-long-identifier-that-overflows-int32";
    useAgentStore.setState({
      selectedAgent: longId,
      agents: [agent(longId, "Long")],
    });
    const { container } = renderWithProviders(<MissionControl />);

    const colors = avatarColors(container);
    expect(colors).toHaveLength(1);
    expect(colors[0]).not.toBe("");
    expect(PALETTE_RGB).toContain(colors[0]);
  });

  it("gives an agent with an empty id the first palette colour", () => {
    useAgentStore.setState({ selectedAgent: "", agents: [agent("", "")] });
    const { container } = renderWithProviders(<MissionControl />);

    expect(avatarColors(container)).toEqual([PALETTE_RGB[0]]);
  });
});

describe("active space highlight", () => {
  it("styles only the current space card differently", () => {
    const { container } = renderWithProviders(<MissionControl />);

    const cards = screen.getAllByRole("button").slice(0, 2);
    expect(tokens(cards[0])).toHaveLength(1);
    expect(tokens(cards[1])).toHaveLength(1);
    expect(tokens(cards[0])[0]).not.toBe(tokens(cards[1])[0]);
    expect(container.querySelectorAll(".count")).toHaveLength(2);
  });

  it("moves the highlight when the current space changes", () => {
    const first = renderWithProviders(<MissionControl />);
    const cardsBefore = screen.getAllByRole("button").slice(0, 2);
    const activeToken = tokens(cardsBefore[0])[0];
    const idleToken = tokens(cardsBefore[1])[0];
    first.unmount();

    useOsWindows.setState({ spaceId: "beta" });
    renderWithProviders(<MissionControl />);

    const cardsAfter = screen.getAllByRole("button").slice(0, 2);
    expect(tokens(cardsAfter[1])[0]).toBe(activeToken);
    expect(tokens(cardsAfter[0])[0]).toBe(idleToken);
  });
});

describe("window counts per space", () => {
  it("reports zero windows for every empty space", () => {
    const { container } = renderWithProviders(<MissionControl />);

    expect(
      Array.from(container.querySelectorAll(".count")).map(
        (c) => c.textContent,
      ),
    ).toEqual(["0 windows", "0 windows"]);
  });

  it("counts the current space from the live order", () => {
    useOsWindows.setState({
      order: ["core.chat", "core.skills"],
      windows: {
        "core.chat": win("core.chat"),
        "core.skills": win("core.skills"),
      },
    });
    const { container } = renderWithProviders(<MissionControl />);

    expect(
      Array.from(container.querySelectorAll(".count")).map(
        (c) => c.textContent,
      ),
    ).toEqual(["2 windows", "0 windows"]);
  });

  it("counts an inactive space from its saved snapshot", () => {
    useOsWindows.setState({
      order: ["core.chat"],
      windows: { "core.chat": win("core.chat") },
      saved: { beta: savedSpace(["a", "b", "c"]), gamma: savedSpace([]) },
    });
    useAgentStore.setState({
      selectedAgent: "alpha",
      agents: [
        agent("alpha", "Alpha"),
        agent("beta", "Beta"),
        agent("gamma", "Gamma"),
      ],
    });
    const { container } = renderWithProviders(<MissionControl />);

    expect(
      Array.from(container.querySelectorAll(".count")).map(
        (c) => c.textContent,
      ),
    ).toEqual(["1 windows", "3 windows", "0 windows"]);
  });

  it("treats a space with no snapshot as having no windows", () => {
    // `saved` has no entry for beta at all, so the optional chain and the
    // nullish fallback both have to hold.
    useOsWindows.setState({ saved: {}, order: [], windows: {} });
    const { container } = renderWithProviders(<MissionControl />);

    expect(
      Array.from(container.querySelectorAll(".count")).map(
        (c) => c.textContent,
      ),
    ).toEqual(["0 windows", "0 windows"]);
  });
});

describe("selecting a space", () => {
  it("switches both the selected agent and the desktop space on click", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.click(screen.getByRole("button", { name: "Beta" }));

    expect(useAgentStore.getState().selectedAgent).toBe("beta");
    expect(useOsWindows.getState().spaceId).toBe("beta");
  });

  it("closes the overlay as part of switching away", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.click(screen.getByRole("button", { name: "Beta" }));

    expect(useOsWindows.getState().missionControlOpen).toBe(false);
  });

  it("closes the overlay when the already active space is selected", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.click(screen.getByRole("button", { name: "Alpha" }));

    const state = useOsWindows.getState();
    expect(state.spaceId).toBe("alpha");
    expect(state.missionControlOpen).toBe(false);
    // An empty desktop is not snapshotted, so switching to itself leaves no
    // stale saved space behind.
    expect(Object.keys(state.saved)).toEqual([]);
  });

  it("moves the current space's windows into saved when switching away", () => {
    useOsWindows.setState({
      order: ["core.chat"],
      windows: { "core.chat": win("core.chat") },
    });
    renderWithProviders(<MissionControl />);

    fireEvent.click(screen.getByRole("button", { name: "Beta" }));

    const state = useOsWindows.getState();
    expect(Object.keys(state.saved)).toEqual(["alpha"]);
    expect(state.saved.alpha.order).toEqual(["core.chat"]);
    // The destination space had no snapshot, so it opens empty.
    expect(state.order).toEqual([]);
  });

  it("activates a space with the Enter key", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.keyDown(screen.getByRole("button", { name: "Beta" }), {
      key: "Enter",
    });

    expect(useAgentStore.getState().selectedAgent).toBe("beta");
    expect(useOsWindows.getState().spaceId).toBe("beta");
  });

  it("activates a space with the Space key", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.keyDown(screen.getByRole("button", { name: "Beta" }), {
      key: " ",
    });

    expect(useOsWindows.getState().spaceId).toBe("beta");
  });

  it("ignores keys that are not activation keys", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.keyDown(screen.getByRole("button", { name: "Beta" }), {
      key: "Tab",
    });

    expect(useOsWindows.getState().spaceId).toBe("alpha");
    expect(useAgentStore.getState().selectedAgent).toBe("alpha");
  });

  it("makes every space card reachable by keyboard", () => {
    renderWithProviders(<MissionControl />);

    screen
      .getAllByRole("button")
      .slice(0, 2)
      .forEach((card) => {
        expect(card).toHaveAttribute("tabindex", "0");
      });
  });
});

describe("open window grid", () => {
  it("shows the hint instead of cards when the space has no windows", () => {
    const { container } = renderWithProviders(<MissionControl />);

    expect(
      screen.getByText("No open windows in this space"),
    ).toBeInTheDocument();
    expect(container.querySelectorAll(".title")).toHaveLength(0);
  });

  it("lists the open windows in store order with their app names", () => {
    useOsWindows.setState({
      order: ["core.chat", "core.skills"],
      windows: {
        "core.chat": win("core.chat"),
        "core.skills": win("core.skills"),
      },
    });
    const { container } = renderWithProviders(<MissionControl />);

    expect(
      Array.from(container.querySelectorAll(".title")).map(
        (t) => t.textContent,
      ),
    ).toEqual(["Chat", "Skills"]);
    expect(screen.queryByText("No open windows in this space")).toBeNull();
  });

  it("draws an icon for every window card", () => {
    useOsWindows.setState({
      order: ["core.chat", "core.skills"],
      windows: {
        "core.chat": win("core.chat"),
        "core.skills": win("core.skills"),
      },
    });
    renderWithProviders(<MissionControl />);

    expect(windowGridIcons()).toBe(2);
  });

  it("skips order entries whose window record is gone", () => {
    // A stale id in `order` must not render an empty card or crash the grid.
    useOsWindows.setState({
      order: ["core.chat", "ghost-missing"],
      windows: { "core.chat": win("core.chat") },
    });
    const { container } = renderWithProviders(<MissionControl />);

    expect(
      Array.from(container.querySelectorAll(".title")).map(
        (t) => t.textContent,
      ),
    ).toEqual(["Chat"]);
  });

  it("falls back to the first catalog app for an unresolvable route id", () => {
    // The guard keeps the overlay usable when a plugin route has been
    // uninstalled while its window id is still in the order.
    useOsWindows.setState({
      order: ["core.chat", "apps.removed-plugin"],
      windows: {
        "core.chat": win("core.chat"),
        "apps.removed-plugin": win("apps.removed-plugin"),
      },
    });
    const { container } = renderWithProviders(<MissionControl />);

    const titles = Array.from(container.querySelectorAll(".title")).map(
      (t) => t.textContent,
    );
    expect(titles).toEqual(["Chat", "Chat"]);
    expect(windowGridIcons()).toBe(2);
  });

  it("focuses the window and closes the overlay on click", () => {
    useOsWindows.setState({
      order: ["core.chat"],
      windows: { "core.chat": win("core.chat", { z: 10, minimized: true }) },
      zCounter: 100,
    });
    renderWithProviders(<MissionControl />);

    fireEvent.click(screen.getByRole("button", { name: "Chat" }));

    const state = useOsWindows.getState();
    expect(state.activeId).toBe("core.chat");
    expect(state.windows["core.chat"].minimized).toBe(false);
    expect(state.windows["core.chat"].z).toBe(101);
    expect(state.missionControlOpen).toBe(false);
  });

  it("focuses the window with the Enter key", () => {
    useOsWindows.setState({
      order: ["core.chat"],
      windows: { "core.chat": win("core.chat") },
    });
    renderWithProviders(<MissionControl />);

    fireEvent.keyDown(screen.getByRole("button", { name: "Chat" }), {
      key: "Enter",
    });

    expect(useOsWindows.getState().activeId).toBe("core.chat");
    expect(useOsWindows.getState().missionControlOpen).toBe(false);
  });

  it("labels each window card with the app name for screen readers", () => {
    useOsWindows.setState({
      order: ["core.skills"],
      windows: { "core.skills": win("core.skills") },
    });
    renderWithProviders(<MissionControl />);

    expect(screen.getByRole("button", { name: "Skills" })).toBeInTheDocument();
  });
});

describe("dismissing the overlay", () => {
  it("closes when the backdrop itself is clicked", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.click(screen.getByRole("dialog"));

    expect(useOsWindows.getState().missionControlOpen).toBe(false);
  });

  it("closes when the close button is clicked", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(useOsWindows.getState().missionControlOpen).toBe(false);
  });

  it("does not close when the click lands on the spaces row background", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.click(spacesRow());

    expect(useOsWindows.getState().missionControlOpen).toBe(true);
  });

  it("does not close when the click lands on the window grid background", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.click(windowsRow());

    expect(useOsWindows.getState().missionControlOpen).toBe(true);
  });

  it("does not close when the click lands on the empty window hint", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.click(screen.getByText("No open windows in this space"));

    expect(useOsWindows.getState().missionControlOpen).toBe(true);
  });

  it("leaves the selection untouched when merely dismissed", () => {
    renderWithProviders(<MissionControl />);

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(useAgentStore.getState().selectedAgent).toBe("alpha");
    expect(useOsWindows.getState().spaceId).toBe("alpha");
  });
});

import {
  describe,
  it,
  expect,
  beforeAll,
  beforeEach,
  afterEach,
  vi,
} from "vitest";
import { Profiler } from "react";
import { fireEvent, screen } from "@testing-library/react";
import { MessageSquare, Inbox } from "lucide-react";
import { renderWithProviders } from "@/test/common_setup";
import WindowFrame from "./WindowFrame";
import { computeSnapRect } from "./snap";
import { useOsWindows, type OsRect, type OsWindow } from "./osWindowStore";

/** jsdom lacks the pointer-capture API used by drag/resize handlers. */
beforeAll(() => {
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
});

function win(id: string, x: number, y: number): OsWindow {
  return {
    id,
    x,
    y,
    w: 700,
    h: 500,
    z: 101,
    minimized: false,
    maximized: false,
  };
}

const winA = win("core.chat", 100, 100);
const winB = win("core.inbox", 400, 300);
const filesWin = { ...win("core.files", 100, 100), w: 800, h: 600 };

function StoreBackedFilesWindow() {
  const currentWin = useOsWindows((state) => state.windows[filesWin.id]);
  return (
    <WindowFrame
      win={currentWin}
      title="Files"
      Icon={Inbox}
      accent="#eab308"
      isMobile={false}
      minW={760}
      minH={480}
    >
      <div>files-content</div>
    </WindowFrame>
  );
}

function expectRenderedRect(frame: HTMLElement, rect: OsRect) {
  expect(frame.style.left).toBe(`${rect.x}px`);
  expect(frame.style.top).toBe(`${rect.y}px`);
  expect(frame.style.width).toBe(`${rect.w}px`);
  expect(frame.style.height).toBe(`${rect.h}px`);
}

beforeEach(() => {
  Object.defineProperty(window, "innerWidth", {
    value: 1920,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(window, "innerHeight", {
    value: 1080,
    configurable: true,
    writable: true,
  });
  useOsWindows.setState({
    windows: { [winA.id]: winA, [winB.id]: winB },
    order: [winA.id, winB.id],
    activeId: winA.id,
    zCounter: 102,
    launcherOpen: false,
    spaceId: "default",
    saved: {},
    missionControlOpen: false,
  });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("WindowFrame drag", () => {
  it("supports keyboard move and resize alternatives", () => {
    renderWithProviders(
      <WindowFrame
        win={winA}
        title="Chat A"
        Icon={MessageSquare}
        accent="#3b82f6"
        isMobile={false}
      >
        <div>a-content</div>
      </WindowFrame>,
    );

    const frame = screen.getByRole("group", { name: "Chat A" });
    fireEvent.keyDown(frame, { key: "ArrowRight", altKey: true });
    expect(useOsWindows.getState().windows["core.chat"].x).toBe(120);

    fireEvent.keyDown(frame, {
      key: "ArrowDown",
      altKey: true,
      shiftKey: true,
    });
    expect(useOsWindows.getState().windows["core.chat"].h).toBe(520);
  });

  it("keeps the store untouched during pointermove and commits once on pointerup", () => {
    const onRenderB = vi.fn();
    renderWithProviders(
      <>
        <WindowFrame
          win={winA}
          title="Chat A"
          Icon={MessageSquare}
          accent="#3b82f6"
          isMobile={false}
        >
          <div>a-content</div>
        </WindowFrame>
        <Profiler id="win-b" onRender={onRenderB}>
          <WindowFrame
            win={winB}
            title="Inbox B"
            Icon={Inbox}
            accent="#eab308"
            isMobile={false}
          >
            <div>b-content</div>
          </WindowFrame>
        </Profiler>
      </>,
    );

    const title = screen.getByText("Chat A");
    // Grab point: 50px right of / 10px below the window origin (100,100).
    fireEvent.pointerDown(title, { pointerId: 1, clientX: 150, clientY: 110 });
    onRenderB.mockClear();
    const windowsBefore = useOsWindows.getState().windows;

    fireEvent.pointerMove(title, { pointerId: 1, clientX: 250, clientY: 200 });
    fireEvent.pointerMove(title, { pointerId: 1, clientX: 350, clientY: 250 });
    fireEvent.pointerMove(title, { pointerId: 1, clientX: 400, clientY: 300 });

    // Transient phase: no store writes, no re-render of the other window.
    expect(useOsWindows.getState().windows).toBe(windowsBefore);
    expect(onRenderB).not.toHaveBeenCalled();

    // The dragged frame moves visually via rAF-coalesced DOM writes.
    vi.advanceTimersByTime(32);
    const frameA = title.parentElement!.parentElement as HTMLElement;
    expect(frameA.style.left).toBe("350px");
    expect(frameA.style.top).toBe("290px");

    fireEvent.pointerUp(title, { pointerId: 1, clientX: 400, clientY: 300 });

    // Single commit with the final geometry.
    const committed = useOsWindows.getState().windows["core.chat"];
    expect(committed).toMatchObject({ x: 350, y: 290 });
    expect(onRenderB).not.toHaveBeenCalled();
  });

  it("restores transient DOM geometry when the drag returns to its origin", () => {
    useOsWindows.setState({
      windows: { [filesWin.id]: filesWin },
      order: [filesWin.id],
      activeId: filesWin.id,
    });
    renderWithProviders(<StoreBackedFilesWindow />);

    const title = screen.getByText("Files");
    const frame = screen.getByRole("group", { name: "Files" });
    fireEvent.pointerDown(title, {
      pointerId: 1,
      clientX: 150,
      clientY: 110,
    });
    fireEvent.pointerMove(title, {
      pointerId: 1,
      clientX: 150,
      clientY: 300,
    });
    vi.advanceTimersByTime(32);
    expect(frame.style.top).toBe("290px");

    fireEvent.pointerMove(title, {
      pointerId: 1,
      clientX: 150,
      clientY: 110,
    });
    fireEvent.pointerUp(title, {
      pointerId: 1,
      clientX: 150,
      clientY: 110,
    });

    expect(useOsWindows.getState().windows[filesWin.id].y).toBe(filesWin.y);
    expect(frame.style.top).toBe(`${filesWin.y}px`);
  });

  it("keeps a dragged window inside the bottom viewport edge", () => {
    useOsWindows.setState({
      windows: { [filesWin.id]: filesWin },
      order: [filesWin.id],
      activeId: filesWin.id,
    });
    renderWithProviders(<StoreBackedFilesWindow />);

    const title = screen.getByText("Files");
    const frame = screen.getByRole("group", { name: "Files" });
    fireEvent.pointerDown(title, {
      pointerId: 1,
      clientX: 150,
      clientY: 110,
    });
    fireEvent.pointerMove(title, {
      pointerId: 1,
      clientX: 150,
      clientY: 1070,
    });
    vi.advanceTimersByTime(32);

    const maxY = window.innerHeight - filesWin.h;
    expect(frame.style.top).toBe(`${maxY}px`);

    fireEvent.pointerUp(title, {
      pointerId: 1,
      clientX: 150,
      clientY: 1070,
    });
    expect(useOsWindows.getState().windows[filesWin.id].y).toBe(maxY);
    expect(Number.parseFloat(frame.style.top) + filesWin.h).toBe(
      window.innerHeight,
    );
  });

  it("keeps DOM geometry aligned with the store across repeated edge snaps", () => {
    useOsWindows.setState({
      windows: { [filesWin.id]: filesWin },
      order: [filesWin.id],
      activeId: filesWin.id,
    });
    renderWithProviders(<StoreBackedFilesWindow />);

    const title = screen.getByText("Files");
    const frame = screen.getByRole("group", { name: "Files" });
    const snapTo = (
      pointerId: number,
      startX: number,
      targetX: number,
      targetY: number,
    ) => {
      fireEvent.pointerDown(title, {
        pointerId,
        clientX: startX,
        clientY: 38,
      });
      fireEvent.pointerMove(title, {
        pointerId,
        clientX: targetX,
        clientY: targetY,
      });
      vi.advanceTimersByTime(32);
      fireEvent.pointerUp(title, {
        pointerId,
        clientX: targetX,
        clientY: targetY,
      });
    };

    const leftRect = computeSnapRect("left", 1920, 1080);
    const rightRect = computeSnapRect("right", 1920, 1080);

    snapTo(1, 150, 5, 400);
    expect(useOsWindows.getState().windows[filesWin.id]).toMatchObject(
      leftRect,
    );
    expectRenderedRect(frame, leftRect);

    snapTo(2, 100, 1915, 496);
    expect(useOsWindows.getState().windows[filesWin.id]).toMatchObject(
      rightRect,
    );
    expectRenderedRect(frame, rightRect);

    snapTo(3, 1060, 5, 596);
    expect(useOsWindows.getState().windows[filesWin.id]).toMatchObject(
      leftRect,
    );
    expectRenderedRect(frame, leftRect);
  });

  it("commits resize once on pointerup with the final rect", () => {
    renderWithProviders(
      <WindowFrame
        win={winA}
        title="Chat A"
        Icon={MessageSquare}
        accent="#3b82f6"
        isMobile={false}
      >
        <div>a-content</div>
      </WindowFrame>,
    );

    // The visible SE grip is the frame's last child (after the 8 edge
    // zones); class names are hashed so structural lookup is used.
    const title = screen.getByText("Chat A");
    const frame = title.parentElement!.parentElement as HTMLElement;
    const grip = frame.lastElementChild as HTMLElement;
    fireEvent.pointerDown(grip, { pointerId: 1, clientX: 800, clientY: 600 });
    const windowsBefore = useOsWindows.getState().windows;

    fireEvent.pointerMove(grip, { pointerId: 1, clientX: 860, clientY: 640 });
    fireEvent.pointerMove(grip, { pointerId: 1, clientX: 900, clientY: 680 });
    expect(useOsWindows.getState().windows).toBe(windowsBefore);

    fireEvent.pointerUp(grip, { pointerId: 1, clientX: 900, clientY: 680 });
    const committed = useOsWindows.getState().windows["core.chat"];
    expect(committed).toMatchObject({ w: 800, h: 580 });
  });

  it("pointercancel finalizes a drag with the last on-screen position", () => {
    renderWithProviders(
      <WindowFrame
        win={winA}
        title="Chat A"
        Icon={MessageSquare}
        accent="#3b82f6"
        isMobile={false}
      >
        <div>a-content</div>
      </WindowFrame>,
    );

    const title = screen.getByText("Chat A");
    fireEvent.pointerDown(title, { pointerId: 1, clientX: 150, clientY: 110 });
    fireEvent.pointerMove(title, { pointerId: 1, clientX: 300, clientY: 220 });

    // System cancels the gesture (touch interruption, app switch).
    fireEvent.pointerCancel(title, {
      pointerId: 1,
      clientX: 300,
      clientY: 220,
    });

    const committed = useOsWindows.getState().windows["core.chat"];
    expect(committed).toMatchObject({ x: 250, y: 210 });
  });

  it("lostpointercapture after pointerup does not commit twice", () => {
    renderWithProviders(
      <WindowFrame
        win={winA}
        title="Chat A"
        Icon={MessageSquare}
        accent="#3b82f6"
        isMobile={false}
      >
        <div>a-content</div>
      </WindowFrame>,
    );

    const title = screen.getByText("Chat A");
    fireEvent.pointerDown(title, { pointerId: 1, clientX: 150, clientY: 110 });
    fireEvent.pointerMove(title, { pointerId: 1, clientX: 300, clientY: 220 });
    fireEvent.pointerUp(title, { pointerId: 1, clientX: 300, clientY: 220 });
    const afterUp = useOsWindows.getState().windows;

    // Browsers fire lostpointercapture after the release cascade.
    fireEvent.lostPointerCapture(title, { pointerId: 1 });

    expect(useOsWindows.getState().windows).toBe(afterUp);
  });
});

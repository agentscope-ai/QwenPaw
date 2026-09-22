import { createPortal } from "react-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelCardSurface } from "./ModelCardSurface";

const preferences = vi.hoisted(() => ({ reducedMotion: false }));
vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("motion/react")>()),
  useReducedMotion: () => preferences.reducedMotion,
}));

function setup(tilt = 7) {
  const onClick = vi.fn();
  const { container } = render(
    <ModelCardSurface tilt={tilt}>
      <button onClick={onClick}>Models</button>
      <input aria-label="Key" />
    </ModelCardSurface>,
  );
  const frame = container.firstElementChild as HTMLDivElement;
  const surface = tilt ? (frame.firstElementChild as HTMLDivElement) : frame;
  const reflection = surface.querySelector(
    '[aria-hidden="true"]',
  ) as HTMLDivElement;
  vi.spyOn(frame, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    width: 300,
    height: 200,
    right: 300,
    bottom: 200,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
  return { frame, surface, reflection, onClick };
}

function pointer(target: Element, type: string, pointerType = "touch") {
  fireEvent(
    target,
    new PointerEvent(type, {
      bubbles: true,
      pointerId: 1,
      isPrimary: true,
      pointerType,
      clientX: 270,
      clientY: 20,
      button: 0,
    }),
  );
}

beforeEach(() => {
  preferences.reducedMotion = false;
});

describe("ModelCardSurface", () => {
  it.each(["pointerup", "pointercancel", "pointerleave", "lostpointercapture"])(
    "follows touch and settles after %s",
    async (endEvent) => {
      const { frame, surface, reflection } = setup();
      pointer(frame, "pointerdown");
      await waitFor(() => {
        expect(surface.style.transform).toContain("rotateX");
        expect(Number(reflection.style.opacity)).toBeGreaterThan(0.5);
        expect(reflection.style.getPropertyValue("--reflection-x")).toBe("90%");
        expect(reflection.style.getPropertyValue("--reflection-y")).toBe("10%");
      });
      pointer(frame, endEvent === "pointerleave" ? "pointerout" : endEvent);
      await waitFor(
        () => {
          expect(Number(reflection.style.opacity)).toBe(0);
          expect(surface.style.transform).not.toContain("rotateX");
        },
        { timeout: 3000 },
      );
    },
  );

  it("supports mouse hover and preserves child controls", async () => {
    const { frame, reflection, onClick } = setup();
    pointer(frame, "pointermove", "mouse");
    await waitFor(() =>
      expect(Number(reflection.style.opacity)).toBeGreaterThan(0),
    );
    fireEvent.click(screen.getByRole("button", { name: "Models" }));
    expect(onClick).toHaveBeenCalledOnce();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "draft" },
    });
    expect(screen.getByRole("textbox")).toHaveValue("draft");
  });

  it("ignores pointer events from portalled dialogs", () => {
    const { container } = render(
      <ModelCardSurface>
        {createPortal(<button>Dialog action</button>, document.body)}
      </ModelCardSurface>,
    );
    const surface = container.firstElementChild!
      .firstElementChild as HTMLElement;
    pointer(
      screen.getByRole("button", { name: "Dialog action" }),
      "pointermove",
      "mouse",
    );
    expect(surface.style.transform).not.toContain("rotateX");
  });

  it.each([3, 5])("uses the requested %s degree tilt", async (tilt) => {
    const { frame, surface } = setup(tilt);
    pointer(frame, "pointermove", "mouse");
    await waitFor(() => {
      const angle = Number(
        surface.style.transform.match(/rotateY\(([-\d.]+)deg\)/)?.[1],
      );
      expect(angle).toBeCloseTo(tilt * 0.8, 1);
    });
  });

  it("keeps panels level and pauses reflections while editing", async () => {
    const { frame, surface, reflection } = setup(0);
    pointer(frame, "pointermove", "mouse");
    await waitFor(() =>
      expect(Number(reflection.style.opacity)).toBeGreaterThan(0.5),
    );
    expect(surface.style.transform).toBe("");
    const input = screen.getByRole("textbox");
    fireEvent.focus(input);
    pointer(frame, "pointermove", "mouse");
    await waitFor(() => expect(Number(reflection.style.opacity)).toBe(0));
    fireEvent.blur(input);
    pointer(input, "pointerdown", "mouse");
    pointer(frame, "pointermove", "mouse");
    expect(Number(reflection.style.opacity)).toBe(0);
    pointer(input, "pointerup", "mouse");
    pointer(frame, "pointermove", "mouse");
    await waitFor(() =>
      expect(Number(reflection.style.opacity)).toBeGreaterThan(0.5),
    );
  });

  it("keeps a static surface for reduced motion", () => {
    preferences.reducedMotion = true;
    const { frame, surface, reflection } = setup();
    pointer(frame, "pointerdown");
    expect(surface.style.transform).toBe("");
    expect(reflection).toBeNull();
  });
});

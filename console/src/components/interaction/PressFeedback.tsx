import { useEffect } from "react";
import { animate, type AnimationPlaybackControls } from "motion";

/** Apply the same interruptible press response to native and library buttons. */
export function PressFeedback() {
  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const animations = new Map<HTMLElement, AnimationPlaybackControls>();
    let pressed: HTMLElement | null = null;
    const target = (event: Event) =>
      event.target instanceof Element
        ? event.target.closest<HTMLElement>(
            ".ant-btn-primary, .qwenpaw-btn-primary, button[data-press]",
          )
        : null;
    const settle = (element: HTMLElement, scale: number) => {
      animations.get(element)?.stop();
      animations.set(
        element,
        animate(
          element,
          { scale },
          {
            type: "spring",
            stiffness: 480,
            damping: scale === 1 ? 26 : 38,
            onComplete: () => animations.delete(element),
          },
        ),
      );
    };
    const release = () => {
      if (pressed) settle(pressed, 1);
      pressed = null;
    };
    const down = (event: PointerEvent | KeyboardEvent) => {
      if (preference.matches) return;
      if (
        event instanceof KeyboardEvent &&
        (event.repeat || !["Enter", " "].includes(event.key))
      )
        return;
      if (
        event instanceof PointerEvent &&
        (!event.isPrimary || event.button !== 0)
      )
        return;
      const element = target(event);
      if (
        !element ||
        element.matches(":disabled, [aria-disabled=true], [aria-busy=true]")
      )
        return;
      release();
      pressed = element;
      settle(element, 0.96);
    };
    const move = (event: PointerEvent) => {
      if (!pressed) return;
      const rect = pressed.getBoundingClientRect();
      if (
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom
      )
        release();
    };
    const keyup = (event: KeyboardEvent) => {
      if (["Enter", " "].includes(event.key)) release();
    };
    const reset = () => {
      if (pressed) pressed.style.scale = "1";
      pressed = null;
      animations.forEach((animation, element) => {
        animation.stop();
        element.style.scale = "1";
      });
      animations.clear();
    };
    document.addEventListener("pointerdown", down, true);
    document.addEventListener("pointermove", move, true);
    document.addEventListener("pointerup", release, true);
    document.addEventListener("pointercancel", release, true);
    document.addEventListener("keydown", down, true);
    document.addEventListener("keyup", keyup, true);
    document.addEventListener("focusout", release, true);
    window.addEventListener("blur", release);
    preference.addEventListener("change", reset);
    return () => {
      reset();
      document.removeEventListener("pointerdown", down, true);
      document.removeEventListener("pointermove", move, true);
      document.removeEventListener("pointerup", release, true);
      document.removeEventListener("pointercancel", release, true);
      document.removeEventListener("keydown", down, true);
      document.removeEventListener("keyup", keyup, true);
      document.removeEventListener("focusout", release, true);
      window.removeEventListener("blur", release);
      preference.removeEventListener("change", reset);
    };
  }, []);
  return null;
}

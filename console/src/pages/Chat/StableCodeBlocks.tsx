import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
type MountBlock = (
  id: string,
  slot: HTMLElement,
  children: ReactNode,
) => () => void;
const MountContext = createContext<MountBlock | null>(null);
interface MountedBlock {
  container: HTMLElement;
  children: ReactNode;
}

/** Portals belong to the message, not Markdown's disposable node tree.
 * Replacing a placeholder moves its existing container without remounting UI.
 * All containers and local state are released when this message unmounts.
 */
export function StableCodeBlocks({ children }: { children: ReactNode }) {
  const containers = useRef(
    new Map<string, { element: HTMLElement; focused: HTMLElement | null }>(),
  );
  const [blocks, setBlocks] = useState(new Map<string, MountedBlock>());
  const mount = useCallback<MountBlock>((id, slot, content) => {
    let target = containers.current.get(id);
    if (!target) {
      const element = document.createElement("span");
      element.style.display = "contents";
      target = { element, focused: null };
      containers.current.set(id, target);
    }
    const container = target.element;
    if (container.parentNode !== slot) slot.appendChild(container);
    // Reparenting DOM can blur a focused form field, even though React state survives.
    if (target.focused && document.activeElement === document.body) {
      target.focused.focus({ preventScroll: true });
    }
    target.focused = null;
    const block = { container, children: content };
    setBlocks((previous) => new Map(previous).set(id, block));
    return () => {
      const active = document.activeElement;
      if (active instanceof HTMLElement && container.contains(active)) {
        target.focused = active;
      }
      // Cleanup and attachment run in one commit. Batched updates retain the
      // portal key and target when Markdown replaces a placeholder.
      setBlocks((previous) => {
        if (previous.get(id) !== block) return previous;
        const next = new Map(previous);
        next.delete(id);
        return next;
      });
    };
  }, []);

  return (
    <MountContext.Provider value={mount}>
      {children}
      {Array.from(blocks, ([id, block]) =>
        createPortal(block.children, block.container, id),
      )}
    </MountContext.Provider>
  );
}

export function CodeBlockSlot({
  id,
  children,
}: {
  id: string;
  children: ReactNode;
}) {
  const mount = useContext(MountContext);
  const slot = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    if (mount && slot.current) return mount(id, slot.current, children);
  }, [mount, id, children]);
  return <span ref={slot} style={{ display: "contents" }} />;
}

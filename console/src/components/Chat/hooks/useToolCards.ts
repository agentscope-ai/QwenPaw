import { useCallback, useMemo, useRef } from "react";
import type { ToolCardComponent, ToolCardRegistry } from "../types";

// ---------------------------------------------------------------------------
// Default card registry (built-in tool cards)
// ---------------------------------------------------------------------------

const defaultRegistry: ToolCardRegistry = {};

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseToolCardsOptions {
  /** External tool cards to register */
  cards?: ToolCardRegistry;
}

export interface UseToolCardsReturn {
  /** Get a card component by tool name */
  getCard: (toolName: string) => ToolCardComponent | null;
  /** The merged registry */
  registry: ToolCardRegistry;
  /** Register a new card at runtime */
  registerCard: (name: string, component: ToolCardComponent) => void;
}

export function useToolCards({
  cards = {},
}: UseToolCardsOptions): UseToolCardsReturn {
  const dynamicCardsRef = useRef<ToolCardRegistry>({});

  const registry = useMemo(
    () => ({
      ...defaultRegistry,
      ...cards,
      ...dynamicCardsRef.current,
    }),
    [cards],
  );

  const getCard = useCallback(
    (toolName: string): ToolCardComponent | null => {
      return registry[toolName] || dynamicCardsRef.current[toolName] || null;
    },
    [registry],
  );

  const registerCard = useCallback(
    (name: string, component: ToolCardComponent) => {
      dynamicCardsRef.current = {
        ...dynamicCardsRef.current,
        [name]: component,
      };
    },
    [],
  );

  return { getCard, registry, registerCard };
}

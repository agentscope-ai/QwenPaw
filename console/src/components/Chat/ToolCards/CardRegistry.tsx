import type { ToolCardComponent, ToolCardRegistry } from "../types";
import DefaultCard from "./DefaultCard";

/**
 * Global card registry for tool result rendering.
 * Cards are matched by tool name — register custom cards to override defaults.
 */
class CardRegistryClass {
  private cards: Map<string, ToolCardComponent> = new Map();

  register(name: string, component: ToolCardComponent): void {
    this.cards.set(name, component);
  }

  unregister(name: string): void {
    this.cards.delete(name);
  }

  get(name: string): ToolCardComponent {
    return this.cards.get(name) || DefaultCard;
  }

  has(name: string): boolean {
    return this.cards.has(name);
  }

  getAll(): ToolCardRegistry {
    const result: ToolCardRegistry = {};
    this.cards.forEach((component, name) => {
      result[name] = component;
    });
    return result;
  }

  /** Bulk register from a registry object */
  registerAll(registry: ToolCardRegistry): void {
    Object.entries(registry).forEach(([name, component]) => {
      this.cards.set(name, component);
    });
  }
}

export const CardRegistry = new CardRegistryClass();

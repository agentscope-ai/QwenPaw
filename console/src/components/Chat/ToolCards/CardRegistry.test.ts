import { describe, it, expect, beforeEach } from "vitest";
import { CardRegistry } from "./CardRegistry";
import type { ToolCardProps } from "../types";

const MockCard: React.FC<ToolCardProps> = () => null;
const AnotherCard: React.FC<ToolCardProps> = () => null;

describe("CardRegistry", () => {
  beforeEach(() => {
    // Clear all registered cards
    const all = CardRegistry.getAll();
    Object.keys(all).forEach((name) => CardRegistry.unregister(name));
  });

  it("register and retrieve a card", () => {
    CardRegistry.register("test_tool", MockCard);
    expect(CardRegistry.has("test_tool")).toBe(true);
    expect(CardRegistry.get("test_tool")).toBe(MockCard);
  });

  it("returns DefaultCard for unregistered tool", () => {
    const card = CardRegistry.get("nonexistent");
    // Should return DefaultCard (the fallback)
    expect(card).toBeDefined();
    expect(card).not.toBe(MockCard);
  });

  it("unregister removes a card", () => {
    CardRegistry.register("test_tool", MockCard);
    CardRegistry.unregister("test_tool");
    expect(CardRegistry.has("test_tool")).toBe(false);
  });

  it("getAll returns all registered cards", () => {
    CardRegistry.register("tool_a", MockCard);
    CardRegistry.register("tool_b", AnotherCard);
    const all = CardRegistry.getAll();
    expect(Object.keys(all)).toHaveLength(2);
    expect(all["tool_a"]).toBe(MockCard);
    expect(all["tool_b"]).toBe(AnotherCard);
  });

  it("registerAll bulk-registers cards", () => {
    CardRegistry.registerAll({
      tool_x: MockCard,
      tool_y: AnotherCard,
    });
    expect(CardRegistry.has("tool_x")).toBe(true);
    expect(CardRegistry.has("tool_y")).toBe(true);
  });

  it("register overwrites existing card", () => {
    CardRegistry.register("tool_a", MockCard);
    CardRegistry.register("tool_a", AnotherCard);
    expect(CardRegistry.get("tool_a")).toBe(AnotherCard);
  });
});

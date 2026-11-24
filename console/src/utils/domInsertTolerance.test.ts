import { beforeEach, describe, expect, it } from "vitest";
import { installDomInsertTolerance } from "./domInsertTolerance";

describe("installDomInsertTolerance", () => {
  beforeEach(() => {
    installDomInsertTolerance();
  });

  it("forwards spec-compliant insertBefore calls untouched", () => {
    const parent = document.createElement("div");
    const first = document.createElement("span");
    const second = document.createElement("span");
    parent.appendChild(first);

    parent.insertBefore(second, first);

    expect(parent.childNodes[0]).toBe(second);
    expect(parent.childNodes[1]).toBe(first);
  });

  it("appends instead of throwing when the reference node was detached", () => {
    const parent = document.createElement("div");
    const detachedRef = document.createElement("span");
    const node = document.createElement("b");

    expect(() => parent.insertBefore(node, detachedRef)).not.toThrow();
    expect(node.parentNode).toBe(parent);
  });

  it("skips the insertion instead of throwing when the reference node has another parent", () => {
    const parent = document.createElement("div");
    const otherParent = document.createElement("div");
    const ref = document.createElement("span");
    otherParent.appendChild(ref);
    const node = document.createElement("b");

    expect(() => parent.insertBefore(node, ref)).not.toThrow();
    // The reference node must not be stolen from its real parent.
    expect(ref.parentNode).toBe(otherParent);
  });

  it("tolerates removing a child that belongs to another parent", () => {
    const parent = document.createElement("div");
    const otherParent = document.createElement("div");
    const child = document.createElement("span");
    otherParent.appendChild(child);

    expect(() => parent.removeChild(child)).not.toThrow();
    expect(child.parentNode).toBe(otherParent);
  });

  it("is idempotent", () => {
    const parent = document.createElement("div");
    const marker = document.createElement("i");
    parent.appendChild(marker);

    installDomInsertTolerance();
    installDomInsertTolerance();

    const node = document.createElement("b");
    parent.insertBefore(node, marker);
    expect(parent.childNodes[0]).toBe(node);
  });
});

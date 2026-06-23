/**
 * install.test.ts — validates the public window.QwenPaw.chat API surface.
 *
 * Focuses on the sugar/wiring layer in install.ts; the underlying registry
 * mechanics (LIFO, audit, disposeAll) are covered by chatExtensions.test.ts.
 */
import { describe, it, expect, beforeEach } from "vitest";
import type React from "react";
import { installHostSdk } from "./install";
import { installHostExternals } from "../hostExternals";
import { chatExtensions } from "../registry/chatExtensions";
import { auditStore } from "../registry/audit";

beforeEach(() => {
  // Reset the window.QwenPaw namespace before each test so installHostSdk
  // attaches fresh references.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).QwenPaw = undefined;
  installHostExternals();
  installHostSdk();
  chatExtensions.__resetForTests();
  auditStore.clear();
});

describe("window.QwenPaw.chat.welcome", () => {
  it("set(partial) writes multiple scalar fields", () => {
    window.QwenPaw.chat!.welcome.set("p1", {
      greeting: "Hi",
      avatar: "/a.png",
    });
    const snap = chatExtensions.getScalarSnapshot();
    expect(snap["welcome.greeting"]?.value).toBe("Hi");
    expect(snap["welcome.avatar"]?.value).toBe("/a.png");
    expect(snap["welcome.nick"]).toBeUndefined();
  });

  it("set() returns a Disposable that reverts every field it wrote", () => {
    const d = window.QwenPaw.chat!.welcome.set("p1", {
      greeting: "Hi",
      avatar: "/a.png",
    });
    d.dispose();
    const snap = chatExtensions.getScalarSnapshot();
    expect(snap["welcome.greeting"]).toBeUndefined();
    expect(snap["welcome.avatar"]).toBeUndefined();
  });

  it("set() from different plugins on different fields coexist (no overwrite)", () => {
    window.QwenPaw.chat!.welcome.set("p1", { greeting: "P1 hi" });
    window.QwenPaw.chat!.welcome.set("p2", { avatar: "/p2.png" });
    const snap = chatExtensions.getScalarSnapshot();
    expect(snap["welcome.greeting"]?.pluginId).toBe("p1");
    expect(snap["welcome.avatar"]?.pluginId).toBe("p2");
  });

  it("render(node) writes a welcome.render scalar", () => {
    window.QwenPaw.chat!.welcome.render("p1", "<plain node>");
    const entry = chatExtensions.getScalarSnapshot()["welcome.render"];
    expect(entry?.pluginId).toBe("p1");
    expect(typeof entry?.value).toBe("function");
  });

  it("render(fn) keeps the fn as-is", () => {
    const fn = () => null as never;
    window.QwenPaw.chat!.welcome.render("p1", fn);
    expect(chatExtensions.getScalarSnapshot()["welcome.render"]?.value).toBe(
      fn,
    );
  });
});

describe("window.QwenPaw.chat.leftHeader", () => {
  it("set(partial) writes header.leftLogo / header.leftTitle", () => {
    window.QwenPaw.chat!.leftHeader.set("p1", {
      title: "MyApp",
      logo: "/logo.png",
    });
    const snap = chatExtensions.getScalarSnapshot();
    expect(snap["header.leftTitle"]?.value).toBe("MyApp");
    expect(snap["header.leftLogo"]?.value).toBe("/logo.png");
  });

  it("render(node) writes header.leftHeader.render scalar", () => {
    window.QwenPaw.chat!.leftHeader.render("p1", "<custom>");
    expect(
      chatExtensions.getScalarSnapshot()["header.leftHeader.render"]?.value,
    ).toBe("<custom>");
  });
});

describe("window.QwenPaw.chat.theme / sender", () => {
  it("theme.set(partial) writes theme.colorPrimary", () => {
    window.QwenPaw.chat!.theme.set("p1", { colorPrimary: "#123456" });
    expect(
      chatExtensions.getScalarSnapshot()["theme.colorPrimary"]?.value,
    ).toBe("#123456");
  });

  it("sender.set(partial) writes placeholder and disclaimer", () => {
    window.QwenPaw.chat!.sender.set("p1", {
      placeholder: "Ask anything",
      disclaimer: "Beta",
    });
    const snap = chatExtensions.getScalarSnapshot();
    expect(snap["sender.placeholder"]?.value).toBe("Ask anything");
    expect(snap["sender.disclaimer"]?.value).toBe("Beta");
  });

  it("sender.addPrefix appends to sender.prefix list", () => {
    window.QwenPaw.chat!.sender.addPrefix("p1", "<icon>");
    const list = chatExtensions.getListSnapshot()["sender.prefix"];
    expect(list).toHaveLength(1);
    expect(list[0].pluginId).toBe("p1");
  });
});

describe("window.QwenPaw.chat.rightHeader / actions", () => {
  it("rightHeader.add appends, never replaces", () => {
    window.QwenPaw.chat!.rightHeader.add("p1", "btn1", { order: 200 });
    window.QwenPaw.chat!.rightHeader.add("p2", "btn2", { order: 300 });
    const list = chatExtensions.getListSnapshot()["header.rightHeader"];
    expect(list.map((e) => e.pluginId)).toEqual(["p1", "p2"]);
  });

  it("actions.add and requestActions.add are separate lists", () => {
    window.QwenPaw.chat!.actions.add("p1", { id: "a1", onClick: () => {} });
    window.QwenPaw.chat!.requestActions.add("p1", {
      id: "r1",
      onClick: () => {},
    });
    const snap = chatExtensions.getListSnapshot();
    expect(snap.actions.map((e) => e.item.id)).toEqual(["a1"]);
    expect(snap.requestActions.map((e) => e.item.id)).toEqual(["r1"]);
  });
});

describe("window.QwenPaw.chat.requestPayload", () => {
  it("add writes a request payload transform list entry", () => {
    const transform = ({ payload }: { payload: Record<string, unknown> }) => ({
      ...payload,
      request_context: { source: "test" },
    });

    window.QwenPaw.chat!.requestPayload.add("p1", transform, {
      id: "p1.payload",
      order: 25,
    });

    const list = chatExtensions.getListSnapshot()["request.payloadTransforms"];
    expect(list).toHaveLength(1);
    expect(list[0].pluginId).toBe("p1");
    expect(list[0].item.id).toBe("p1.payload");
    expect(list[0].item.order).toBe(25);
    expect(list[0].item.transform).toBe(transform);
  });
});

describe("window.QwenPaw.host.* hooks attached", () => {
  it("attaches the four hooks + fetch + imperative getters", () => {
    expect(typeof window.QwenPaw.host.useTheme).toBe("function");
    expect(typeof window.QwenPaw.host.useLocale).toBe("function");
    expect(typeof window.QwenPaw.host.useSelectedAgent).toBe("function");
    expect(typeof window.QwenPaw.host.useCurrentSession).toBe("function");
    expect(typeof window.QwenPaw.host.getSelectedAgentId).toBe("function");
    expect(typeof window.QwenPaw.host.getCurrentSessionId).toBe("function");
    expect(typeof window.QwenPaw.host.fetch).toBe("function");
  });
});

describe("window.QwenPaw.audit", () => {
  it("overrides() returns the audit ring buffer", () => {
    window.QwenPaw.chat!.welcome.set("p1", { greeting: "Hi" });
    const records = window.QwenPaw.audit!.overrides();
    expect(records.length).toBeGreaterThan(0);
    expect(records.some((r) => r.field === "welcome.greeting")).toBe(true);
  });
});

describe("window.QwenPaw.chat.request / response", () => {
  it("request.render writes a request.render scalar", () => {
    const fn = ({ fallback }: { fallback: () => React.ReactElement }) =>
      fallback();
    window.QwenPaw.chat!.request.render("p1", fn);
    expect(chatExtensions.getScalarSnapshot()["request.render"]?.value).toBe(
      fn,
    );
  });

  it("response.render writes a response.render scalar", () => {
    const fn = ({ fallback }: { fallback: () => React.ReactElement }) =>
      fallback();
    window.QwenPaw.chat!.response.render("p1", fn);
    expect(chatExtensions.getScalarSnapshot()["response.render"]?.value).toBe(
      fn,
    );
  });

  it("response.set writes the assistant identity through welcome avatar/nick", () => {
    window.QwenPaw.chat!.response.set("p1", {
      avatar: "/bot.png",
      nick: "My Bot",
    });

    const snap = chatExtensions.getScalarSnapshot();
    expect(snap["welcome.avatar"]?.value).toBe("/bot.png");
    expect(snap["welcome.nick"]?.value).toBe("My Bot");
  });

  it("request.prepend / append append to their respective lists", () => {
    const r1 = () => null;
    const r2 = () => null;
    window.QwenPaw.chat!.request.prepend("p1", r1, { id: "p1.pre" });
    window.QwenPaw.chat!.request.append("p1", r2, { id: "p1.post" });

    const snap = chatExtensions.getListSnapshot();
    expect(snap["request.prepend"].map((e) => e.item.id)).toEqual(["p1.pre"]);
    expect(snap["request.append"].map((e) => e.item.id)).toEqual(["p1.post"]);
  });

  it("response.prepend / append from multiple plugins coexist", () => {
    window.QwenPaw.chat!.response.prepend("p1", () => null, { id: "a" });
    window.QwenPaw.chat!.response.prepend("p2", () => null, { id: "b" });
    expect(
      chatExtensions
        .getListSnapshot()
        ["response.prepend"].map((e) => e.pluginId),
    ).toEqual(["p1", "p2"]);
  });

  it("returned Disposables actually clean up the slots", () => {
    const d = window.QwenPaw.chat!.request.prepend("p1", () => null, {
      id: "x",
    });
    expect(chatExtensions.getListSnapshot()["request.prepend"]).toHaveLength(1);
    d.dispose();
    expect(chatExtensions.getListSnapshot()["request.prepend"]).toHaveLength(0);
  });
});

describe("disposeAll", () => {
  it("clears every registration from the named plugin", () => {
    window.QwenPaw.chat!.welcome.set("p1", { greeting: "Hi", avatar: "/x" });
    window.QwenPaw.chat!.actions.add("p1", {
      id: "p1.a",
      onClick: () => {},
    });
    window.QwenPaw.chat!.actions.add("p2", {
      id: "p2.a",
      onClick: () => {},
    });

    window.QwenPaw.chat!.disposeAll("p1");

    const snap = chatExtensions.getScalarSnapshot();
    expect(snap["welcome.greeting"]).toBeUndefined();
    expect(snap["welcome.avatar"]).toBeUndefined();
    expect(
      chatExtensions.getListSnapshot().actions.map((e) => e.item.id),
    ).toEqual(["p2.a"]);
  });
});

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { PushMessageCard } from "./PushMessageCard";
import type { PushMessage } from "../types";

// `normalizeCronTaskName` is module-private, so the title rewriting is observed
// through the interpolation payload handed to `t("inbox.pushCronHeader", opts)`.
// Recording `t` calls therefore doubles as the assertion surface for that
// helper; the key itself is returned verbatim so DOM text stays greppable.
const tCalls: Array<{ key: string; opts: unknown }> = [];

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: unknown) => {
      tCalls.push({ key, opts });
      return key;
    },
  }),
}));

const CRON_HEADER_KEY = "inbox.pushCronHeader";

/** Interpolation payloads passed to `inbox.pushCronHeader`, in call order. */
const cronNames = (): unknown[] =>
  tCalls.filter((c) => c.key === CRON_HEADER_KEY).map((c) => c.opts);

const message = (over: Partial<PushMessage> = {}): PushMessage => ({
  id: "m1",
  channelType: "wechat",
  channelName: "WeCom",
  title: "raw title",
  content: "body text",
  sender: { userId: "u1", username: "alice" },
  createdAt: new Date("2026-09-27T10:00:00+08:00"),
  read: false,
  ...over,
});

interface MountResult {
  container: HTMLElement;
  onView: ReturnType<typeof vi.fn>;
  onDelete: ReturnType<typeof vi.fn>;
  onMarkAsRead: ReturnType<typeof vi.fn>;
  onSelectChange: ReturnType<typeof vi.fn>;
}

/**
 * Renders the card with every callback wired to a spy.
 * `selectable` keeps `onSelectChange` off entirely so the checkbox arm that
 * renders `null` is reachable; passing the prop as `undefined` would not,
 * because the component tests the identifier for truthiness.
 */
const mount = (
  msg: PushMessage,
  extra: { selected?: boolean; selectable?: boolean } = {},
): MountResult => {
  const { selected, selectable = true } = extra;
  tCalls.length = 0;
  const onView = vi.fn();
  const onDelete = vi.fn();
  const onMarkAsRead = vi.fn();
  const onSelectChange = vi.fn();
  const shared = { message: msg, onView, onDelete, onMarkAsRead };
  const { container } = render(
    selectable ? (
      <PushMessageCard
        {...shared}
        onSelectChange={onSelectChange}
        selected={selected}
      />
    ) : (
      <PushMessageCard {...shared} selected={selected} />
    ),
  );
  return {
    container: container as HTMLElement,
    onView,
    onDelete,
    onMarkAsRead,
    onSelectChange,
  };
};

const card = (container: HTMLElement) =>
  container.querySelector(".ant-card") as HTMLElement;
const tag = (container: HTMLElement) => container.querySelector(".ant-tag");
const checkboxInput = (container: HTMLElement) =>
  container.querySelector(".ant-checkbox-input") as HTMLInputElement;
const dangerButton = (container: HTMLElement) =>
  container.querySelector("button.ant-btn-dangerous") as HTMLElement;
const avatar = (container: HTMLElement) =>
  container.querySelector(".ant-avatar") as HTMLElement;

/** Opens the delete Popconfirm and returns its cancel/confirm buttons. */
const openPopconfirm = (container: HTMLElement) => {
  fireEvent.click(dangerButton(container));
  const popover = document.querySelector(".ant-popover") as HTMLElement;
  const buttons = [...popover.querySelectorAll("button")];
  return {
    popover,
    // Located by antd's own styling role, never by positional index: the
    // button order inside the popover is an antd layout detail.
    cancel: buttons.find((b) =>
      /ant-btn-default/.test(b.className),
    ) as HTMLElement,
    confirm: buttons.find((b) =>
      /ant-btn-primary/.test(b.className),
    ) as HTMLElement,
  };
};

beforeEach(() => {
  tCalls.length = 0;
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("PushMessageCard cron title rewriting", () => {
  it("routes a cron message title through the cron header key", () => {
    const { container } = mount(
      message({ title: "plain title", metadata: { sourceType: "cron" } }),
    );
    expect(container.querySelector("h4")?.textContent).toBe(CRON_HEADER_KEY);
    expect(cronNames()).toEqual([{ name: "plain title" }]);
  });

  it.each([
    ["cron result: nightly", "nightly"],
    ["Cron Result: nightly", "nightly"],
    ["CRON RESULT: nightly", "nightly"],
    ["heartbeat result: heartbeat job", "heartbeat job"],
    ["Heartbeat Result: heartbeat job", "heartbeat job"],
  ])("strips the english prefix %j case-insensitively", (title, expected) => {
    mount(message({ title, metadata: { sourceType: "cron" } }));
    expect(cronNames()).toEqual([{ name: expected }]);
  });

  it.each([
    ["定时任务结果: nightly", "nightly"],
    ["定时任务结果：nightly", "nightly"],
    ["心跳结果：heartbeat job", "heartbeat job"],
    ["心跳结果:heartbeat job", "heartbeat job"],
  ])("strips the chinese prefix %j", (title, expected) => {
    mount(message({ title, metadata: { sourceType: "cron" } }));
    expect(cronNames()).toEqual([{ name: expected }]);
  });

  it.each([
    ["cron result：nightly", "nightly"],
    ["cron result : nightly", "nightly"],
    ["cron result:   spaced   ", "spaced"],
  ])("accepts a fullwidth colon or padding around %j", (title, expected) => {
    mount(message({ title, metadata: { sourceType: "cron" } }));
    expect(cronNames()).toEqual([{ name: expected }]);
  });

  it.each([
    // `results` (plural) and `cronresult` (no space) must survive: both prove
    // the prefix match is anchored to the exact phrase rather than a prefix
    // substring, which a looser pattern would silently swallow.
    ["cron results: nightly", "cron results: nightly"],
    ["cronresult: nightly", "cronresult: nightly"],
    ["plain title", "plain title"],
    ["", ""],
    ["   ", ""],
  ])("leaves %j untouched", (title, expected) => {
    mount(message({ title, metadata: { sourceType: "cron" } }));
    expect(cronNames()).toEqual([{ name: expected }]);
  });

  it("does not strip the prefix when leading whitespace precedes it", () => {
    // Observed contract: the anchor is `^`, so a leading space defeats the
    // prefix match, while the trailing `.trim()` still runs. The visible
    // result is the trimmed original string, prefix included.
    mount(
      message({
        title: "  cron result: nightly",
        metadata: { sourceType: "cron" },
      }),
    );
    expect(cronNames()).toEqual([{ name: "cron result: nightly" }]);
  });

  it("shows the raw title when the message is not from cron", () => {
    const { container } = mount(
      message({
        title: "cron result: nightly",
        metadata: { sourceType: "manual" },
      }),
    );
    expect(container.querySelector("h4")?.textContent).toBe(
      "cron result: nightly",
    );
    expect(cronNames()).toEqual([]);
  });

  it.each([["CRON"], ["Cron"], ["cRoN"]])(
    "treats sourceType %j as cron after lowercasing",
    (sourceType) => {
      const { container } = mount(
        message({ title: "cron result: nightly", metadata: { sourceType } }),
      );
      expect(container.querySelector("h4")?.textContent).toBe(CRON_HEADER_KEY);
      expect(cronNames()).toEqual([{ name: "nightly" }]);
    },
  );

  it("does not treat a padded sourceType as cron", () => {
    // Observed contract: sourceType is lowercased but never trimmed, so
    // " cron " misses the equality check and the raw title is shown.
    const { container } = mount(
      message({
        title: "cron result: nightly",
        metadata: { sourceType: " cron " },
      }),
    );
    expect(container.querySelector("h4")?.textContent).toBe(
      "cron result: nightly",
    );
    expect(cronNames()).toEqual([]);
  });

  it.each([
    ["metadata absent", undefined],
    ["metadata empty", {}],
    ["sourceType absent", { sourceId: "s1" }],
    ["sourceType empty string", { sourceType: "" }],
  ])("falls back to the raw title when %s", (_label, metadata) => {
    const { container } = mount(
      message({ title: "cron result: nightly", metadata }),
    );
    expect(container.querySelector("h4")?.textContent).toBe(
      "cron result: nightly",
    );
    expect(cronNames()).toEqual([]);
  });

  it("renders the message body and the channel name", () => {
    const { container } = mount(
      message({ content: "the body", channelName: "Slack HQ" }),
    );
    expect(container.querySelector("p")?.textContent).toBe("the body");
    expect(container.textContent).toContain("Slack HQ");
  });

  it("renders the sender username behind the translation key", () => {
    const { container } = mount(
      message({ sender: { userId: "u", username: "bob" } }),
    );
    expect(container.textContent).toContain("inbox.from");
    expect(container.textContent).toContain("bob");
  });

  it("never invokes onMarkAsRead", () => {
    // The prop is part of the public interface but the component body does not
    // read it; pinning that keeps a future wiring change visible as a failure.
    const { onMarkAsRead, container } = mount(message());
    fireEvent.click(card(container));
    expect(onMarkAsRead).not.toHaveBeenCalled();
  });
});

describe("PushMessageCard read state", () => {
  it("marks an unread message with both the card class and the dot", () => {
    const { container } = mount(message({ read: false }));
    expect(card(container).className).toMatch(/unread/);
    expect(container.querySelectorAll("[class*=unreadDot]").length).toBe(1);
  });

  it("renders a read message with neither the card class nor the dot", () => {
    const { container } = mount(message({ read: true }));
    expect(card(container).className).not.toMatch(/unread/);
    expect(container.querySelectorAll("[class*=unreadDot]").length).toBe(0);
  });
});

describe("PushMessageCard priority tag", () => {
  // The tuple type is spelled out because `it.each` would otherwise widen the
  // first element to `string`, which no longer satisfies the literal union
  // that `PushMessage["metadata"]["priority"]` declares.
  const priorityCases: Array<
    [NonNullable<PushMessage["metadata"]>["priority"], string, boolean, boolean]
  > = [
    ["urgent", "URGENT", true, false],
    ["high", "HIGH", false, true],
    ["low", "LOW", false, true],
  ];

  it.each(priorityCases)(
    "renders a %s priority as %s with error=%s warning=%s",
    (priority, text, isError, isWarning) => {
      const { container } = mount(message({ metadata: { priority } }));
      const el = tag(container);
      expect(el?.textContent).toBe(text);
      expect(el?.classList.contains("ant-tag-error")).toBe(isError);
      expect(el?.classList.contains("ant-tag-warning")).toBe(isWarning);
    },
  );

  it("hides the tag for a normal priority", () => {
    const { container } = mount(message({ metadata: { priority: "normal" } }));
    expect(tag(container)).toBeNull();
  });

  it.each([
    ["metadata absent", undefined],
    ["priority absent", {}],
  ])("hides the tag when %s", (_label, metadata) => {
    const { container } = mount(message({ metadata }));
    expect(tag(container)).toBeNull();
  });
});

describe("PushMessageCard channel presentation", () => {
  it.each([
    ["wechat", "rgb(7, 193, 96)"],
    ["slack", "rgb(74, 21, 75)"],
    ["telegram", "rgb(0, 136, 204)"],
    ["discord", "rgb(88, 101, 242)"],
    ["email", "rgb(234, 67, 53)"],
    ["memory", "rgb(124, 58, 237)"],
    ["heartbeat", "rgb(88, 101, 242)"],
    ["skill", "rgb(22, 119, 255)"],
  ])("paints the %s avatar with %s and one icon", (channelType, bg) => {
    const { container } = mount(
      message({ channelType: channelType as PushMessage["channelType"] }),
    );
    expect(avatar(container).style.backgroundColor).toBe(bg);
    expect(container.querySelectorAll(".ant-avatar svg").length).toBe(1);
  });
});

describe("PushMessageCard selection", () => {
  it("omits the checkbox when no selection handler is supplied", () => {
    const { container } = mount(message(), { selectable: false });
    expect(container.querySelectorAll(".ant-checkbox").length).toBe(0);
  });

  it("renders the checkbox when a selection handler is supplied", () => {
    const { container } = mount(message());
    expect(container.querySelectorAll(".ant-checkbox").length).toBe(1);
  });

  it("defaults the checkbox to unchecked", () => {
    // `selected` is omitted entirely so the default-arg path is what runs.
    const { container } = mount(message(), { selected: undefined });
    expect(checkboxInput(container).checked).toBe(false);
  });

  it("reflects an explicitly selected row", () => {
    const { container } = mount(message(), { selected: true });
    expect(checkboxInput(container).checked).toBe(true);
  });

  it("reflects an explicitly unselected row", () => {
    const { container } = mount(message(), { selected: false });
    expect(checkboxInput(container).checked).toBe(false);
  });

  it("reports the row id and the new checked state on toggle", () => {
    const { container, onSelectChange, onView } = mount(
      message({ id: "row-7" }),
    );
    fireEvent.click(checkboxInput(container));
    expect(onSelectChange).toHaveBeenCalledTimes(1);
    expect(onSelectChange).toHaveBeenCalledWith("row-7", true);
    // The click must not bubble into the card's own open handler.
    expect(onView).not.toHaveBeenCalled();
  });
});

describe("PushMessageCard interactions", () => {
  it("opens the message when the card body is clicked", () => {
    const { container, onView, onDelete } = mount(message({ id: "open-me" }));
    fireEvent.click(card(container));
    expect(onView).toHaveBeenCalledTimes(1);
    expect(onView).toHaveBeenCalledWith("open-me");
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("does not open the message when the delete button is clicked", () => {
    const { container, onView } = mount(message());
    fireEvent.click(dangerButton(container));
    expect(onView).not.toHaveBeenCalled();
  });

  it("asks for confirmation with the translated prompt", () => {
    const { container } = mount(message());
    const { popover } = openPopconfirm(container);
    expect(popover.textContent).toContain("inbox.deleteMessageConfirm");
    expect(popover.textContent).toContain("common.confirm");
    expect(popover.textContent).toContain("common.cancel");
  });

  it("deletes the message on confirm without opening it", () => {
    const { container, onDelete, onView } = mount(message({ id: "del-me" }));
    const { confirm } = openPopconfirm(container);
    fireEvent.click(confirm);
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith("del-me");
    expect(onView).not.toHaveBeenCalled();
  });

  it("keeps the message on cancel without opening it", () => {
    const { container, onDelete, onView } = mount(message());
    const { cancel } = openPopconfirm(container);
    fireEvent.click(cancel);
    expect(onDelete).not.toHaveBeenCalled();
    expect(onView).not.toHaveBeenCalled();
  });
});

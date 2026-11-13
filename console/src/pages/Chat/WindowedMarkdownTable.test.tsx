import { act, cleanup, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import XMarkdown from "@ant-design/x-markdown";
import {
  WindowedMarkdownTable,
  WindowedMarkdownTableBody,
} from "./WindowedMarkdownTable";
import { revealCachedMessage } from "./MeasuredMessageWindow";

afterEach(cleanup);

it("keeps valid table structure and reveals the final row with bounded DOM", () => {
  const content =
    "| Module | State |\n| --- | --- |\n" +
    Array.from({ length: 1000 }, (_, i) => `| module-${i} | verified |`).join(
      "\n",
    );
  const view = render(
    <div data-history-message-window="true">
      <XMarkdown
        content={content}
        components={{
          table: WindowedMarkdownTable,
          tbody: WindowedMarkdownTableBody,
        }}
      />
    </div>,
  );
  expect(
    view.container.querySelectorAll("tbody > tr[data-window-row]"),
  ).toHaveLength(32);
  expect(
    view.container
      .querySelector("tbody > tr > td[colspan]")
      ?.getAttribute("colspan"),
  ).toBe("2");
  expect(view.container.querySelectorAll("tbody > div")).toHaveLength(0);
  act(() => {
    expect(
      revealCachedMessage(
        view.container.firstElementChild as HTMLElement,
        "table-row:999",
        () => {},
      ),
    ).toBe(true);
  });
  expect(view.getByText("module-999")).toBeInTheDocument();
  expect(
    view.container.querySelectorAll("tbody > tr[data-window-row]"),
  ).toHaveLength(32);
});

it("leaves a small table fully rendered", () => {
  const view = render(
    <XMarkdown
      content={"| A | B |\n| --- | --- |\n| one | two |"}
      components={{
        table: WindowedMarkdownTable,
        tbody: WindowedMarkdownTableBody,
      }}
    />,
  );
  expect(view.getByText("two")).toBeInTheDocument();
  expect(
    view.container.querySelector("[data-measured-message-window]"),
  ).toBeNull();
});

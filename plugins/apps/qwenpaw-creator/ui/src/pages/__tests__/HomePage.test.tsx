import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import * as api from "@/api/creator";
import HomePage from "@/pages/HomePage";
import { installMockFetch } from "@/test/mockFetch";

it("keeps the latest sort when an earlier list arrives last", async () => {
  installMockFetch([
    { match: "/models/config", response: { ok: false, status: 503 } },
  ]);
  type List = Awaited<ReturnType<typeof api.listProjects>>;
  const row = (name: string): List["items"][number] => ({
    scenario: "general",
    aspectRatio: "16:9",
    resolution: "1080p",
    projectId: name,
    name,
    description: "",
    createdAt: "2026-11-01T00:00:00Z",
    updatedAt: "2026-11-01T00:00:00Z",
    status: "IDLE",
  });
  const page = (name: string): List => ({
    items: [row(name)],
    limit: 100,
    offset: 0,
  });
  let completeOld!: (value: List) => void;
  const first = new Promise<List>((resolve) => {
    completeOld = resolve;
  });
  const list = vi
    .spyOn(api, "listProjects")
    .mockImplementation((_limit, _offset, sort) =>
      sort === "name" ? Promise.resolve(page("Latest sort")) : first,
    );
  try {
    render(
      <MemoryRouter initialEntries={["/?view=projects"]}>
        <HomePage />
      </MemoryRouter>,
    );
    fireEvent.change(await screen.findByRole("combobox"), {
      target: { value: "name" },
    });
    await screen.findByRole("heading", { name: "Latest sort" });
    await act(async () => {
      completeOld(page("Obsolete sort"));
    });
    expect(screen.queryByRole("heading", { name: "Obsolete sort" })).toBeNull();
    expect(
      screen.getByRole("heading", { name: "Latest sort" }),
    ).toBeInTheDocument();
    expect(list.mock.calls.map(([, , sort]) => sort)).toEqual([
      "updated_at",
      "name",
    ]);
  } finally {
    list.mockRestore();
  }
});

it("reloads the list after a project disappears while the same GET is in flight", async () => {
  const items = [
    {
      projectId: "gone",
      name: "Gone",
      createdAt: "2026-11-01",
      updatedAt: "2026-11-01",
    },
  ];
  const { fetchMock } = installMockFetch([
    {
      match: "/projects/gone/copy",
      response: { ok: false, status: 404, json: {} },
    },
    { match: "/projects?", response: { json: { items } } },
    { match: "/models/config", response: { ok: false, status: 503 } },
  ]);
  let finishOld!: (value: Response) => void;
  const old = new Promise<Response>((resolve) => {
    finishOld = resolve;
  });
  let sortedReads = 0;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, options?: RequestInit) => {
    if (!String(input).includes("sort_by=name"))
      return fetchMock(input, options);
    sortedReads++;
    return sortedReads === 1
      ? old
      : Promise.resolve(Response.json({ items: [] }));
  });
  render(
    <MemoryRouter initialEntries={["/?view=projects"]}>
      <HomePage />
    </MemoryRouter>,
  );
  await screen.findByRole("heading", { name: "Gone" });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "name" } });
  expect(sortedReads).toBe(1);
  fireEvent.click(screen.getByRole("button", { name: /复制.*Gone/ }));
  await vi.waitFor(() => expect(sortedReads).toBe(2));
  await act(async () => {
    finishOld(Response.json({ items }));
  });
  expect(screen.queryByRole("heading", { name: "Gone" })).toBeNull();
});

import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";
import HomePage from "@/pages/HomePage";
import { creatorStatusLabel } from "@/lib/creatorPresentation";
import { installMockFetch } from "@/test/mockFetch";

it("reads only missing task summaries and offers explicit recovery for newly available history", async () => {
  const project = {
    description: "",
    createdAt: "2026-11-01T00:00:00Z",
    updatedAt: "2026-11-02T00:00:00Z",
    status: "IDLE",
  };
  const { calls } = installMockFetch([
    { match: "/models/config", response: { ok: false, status: 503 } },
    {
      match: "/projects?",
      response: {
        json: {
          items: [
            {
              ...project,
              name: "Active",
              projectId: "active",
              hasActiveTask: true,
            },
            {
              ...project,
              name: "Idle",
              projectId: "idle",
              hasActiveTask: false,
            },
            { ...project, name: "Legacy", projectId: "legacy" },
          ],
        },
      },
    },
    {
      match: "/projects/legacy/tasks",
      response: { json: { items: [{ status: "QUEUED" }] } },
    },
    {
      match: "/storage/profile",
      response: {
        json: {
          projects: [
            {
              projectId: "idle",
              pendingReclaimBytes: 128,
              reclaimConfirmedAt: "2026-10-01",
            },
          ],
        },
      },
    },
  ]);
  render(
    <MemoryRouter initialEntries={["/?view=projects"]}>
      <HomePage />
    </MemoryRouter>,
  );
  for (const name of ["Active", "Legacy"]) {
    const card = (await screen.findByRole("heading", { name })).closest(
      '[role="button"]',
    ) as HTMLElement;
    expect(
      within(card).getByText(creatorStatusLabel("RUNNING")),
    ).toBeInTheDocument();
  }
  const idle = (await screen.findByRole("heading", { name: "Idle" })).closest(
    '[role="button"]',
  ) as HTMLElement;
  expect(
    within(idle).getByText(creatorStatusLabel("IDLE")),
  ).toBeInTheDocument();
  expect(
    within(idle).getByRole("button", { name: "确认并释放" }),
  ).toBeInTheDocument();
  expect(
    calls.filter((call) => call.url.endsWith("/tasks")).map((call) => call.url),
  ).toEqual([expect.stringContaining("/projects/legacy/tasks")]);
  expect(calls.some((call) => call.url.includes("reclaim-history"))).toBe(
    false,
  );
});

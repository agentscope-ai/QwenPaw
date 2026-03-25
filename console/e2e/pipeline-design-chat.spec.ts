import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

async function setupApiMocks(page: Page) {
  let createdChatCount = 0;
  const chats: Array<Record<string, unknown>> = [
    {
      id: "old-session-1",
      name: "Old Session",
      session_id: "old-session-1",
      user_id: "default",
      channel: "console",
      meta: {},
      status: "idle",
      created_at: "2026-03-20T00:00:00Z",
      updated_at: "2026-03-20T00:00:00Z",
    },
  ];

  page.on("pageerror", (error: Error) => {
    console.error("[e2e] pageerror:", error.message);
  });

  await page.route("**/api/**", async (route: Route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname.replace(/^\/console(?=\/api\/)/, "");

    // Only mock backend API calls; let frontend module paths under /src/api/* pass through.
    if (!pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }

    if (pathname === "/api/auth/status") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: false }),
      });
      return;
    }

    if (pathname === "/api/agents") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          agents: [
            {
              id: "default",
              name: "Default",
              description: "",
              workspace_dir: "/tmp/default",
              projects: [
                {
                  id: "p1",
                  name: "Project One",
                  description: "",
                  status: "active",
                  workspace_dir: "/tmp/default",
                  data_dir: "/tmp/default/data",
                  metadata_file: "PROJECT.md",
                  tags: [],
                  updated_time: "2026-03-23T00:00:00Z",
                },
              ],
            },
          ],
        }),
      });
      return;
    }

    if (pathname === "/api/agents/default/projects/p1/pipelines/templates") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "books-alignment-v1",
            name: "Books Alignment",
            version: "0.1.0",
            description: "",
            steps: [],
          },
        ]),
      });
      return;
    }

    if (pathname === "/api/agents/default/pipelines/templates") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
      return;
    }

    if (pathname === "/api/agents/default/projects/p1/pipelines/runs") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
      return;
    }

    if (pathname === "/api/chats" && route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(chats),
      });
      return;
    }

    if (pathname === "/api/chats" && route.request().method() === "POST") {
      createdChatCount += 1;
      const bodyText = route.request().postData() || "{}";
      const body = JSON.parse(bodyText);
      const createdId = `created-chat-${createdChatCount}`;
      const createdChat = {
        id: createdId,
        name: body.name || "Pipeline Design",
        session_id: body.session_id || createdId,
        user_id: body.user_id || "default",
        channel: body.channel || "console",
        meta: body.meta || {},
        status: "idle",
        created_at: "2026-03-25T00:00:00Z",
        updated_at: "2026-03-25T00:00:00Z",
      };
      chats.unshift(createdChat);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(createdChat),
      });
      return;
    }

    if (pathname.startsWith("/api/chats/")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          messages: [],
          status: "idle",
          has_more: false,
          total: 0,
        }),
      });
      return;
    }

    if (pathname === "/api/providers/active-models") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          active_llm: {
            provider_id: "mock",
            model: "mock-model",
          },
        }),
      });
      return;
    }

    if (pathname === "/api/console/chat") {
      await route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          Connection: "keep-alive",
          "Cache-Control": "no-cache",
        },
        body: "data: {\"status\":\"ok\"}\n\n",
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    });
  });
}

test("health: pipelines page renders design entry", async ({ page }) => {
  test.setTimeout(60_000);

  await setupApiMocks(page);
  await page.goto("/pipelines");

  const openDesignBtn = page.getByTestId("pipeline-open-design-chat");
  await expect(openDesignBtn).toBeVisible({ timeout: 30_000 });
});

test("behavior: pipeline design entry opens inline edit and keeps dedicated chat id", async ({ page }) => {
  test.setTimeout(90_000);

  await setupApiMocks(page);

  await page.goto("/pipelines");

  const openDesignBtn = page.getByTestId("pipeline-open-design-chat");
  try {
    await expect(openDesignBtn).toBeVisible({ timeout: 30_000 });
  } catch (error) {
    const currentUrl = page.url();
    const bodyText = (await page.locator("body").innerText()).slice(0, 500);
    console.error("[e2e] missing button url:", currentUrl);
    console.error("[e2e] missing button body(head):", bodyText);
    throw error;
  }

  const createChatRequest = page.waitForRequest((request) => {
    return request.method() === "POST" && request.url().includes("/api/chats");
  });
  await openDesignBtn.click();

  const request = await createChatRequest;
  expect(request.postDataJSON()).toMatchObject({
    name: "Pipeline Design",
    user_id: "default",
    channel: "console",
  });

  await expect(page).toHaveURL(/\/pipelines(?:\?.*)?$/);
  const openFullChatBtn = page.getByRole("button", {
    name: /Open Full Chat|完整聊天/i,
  });
  await expect(openFullChatBtn).toBeVisible({ timeout: 20_000 });

  await openFullChatBtn.click();
  await expect(page).toHaveURL(/\/chat\/[^/?]+/);

  const urlAfterCreate = page.url();
  const createdChatId = urlAfterCreate.match(/\/chat\/([^/?]+)/)?.[1] || "";
  expect(createdChatId).toBeTruthy();
  await page.waitForTimeout(1200);

  await expect(page).toHaveURL(new RegExp(`/chat/${createdChatId}(?:\\?.*)?$`));
  expect(urlAfterCreate).not.toContain("old-session-1");
});

test("behavior: each pipeline create opens a new chat id", async ({ page }) => {
  test.setTimeout(90_000);

  await setupApiMocks(page);

  await page.goto("/pipelines");

  const openDesignBtn = page.getByTestId("pipeline-open-design-chat");
  await expect(openDesignBtn).toBeVisible({ timeout: 30_000 });

  const createChatRequestFirst = page.waitForRequest((request) => {
    return request.method() === "POST" && request.url().includes("/api/chats");
  });
  await openDesignBtn.click();
  await createChatRequestFirst;
  const openFullChatBtnFirst = page.getByRole("button", {
    name: /Open Full Chat|完整聊天/i,
  });
  await expect(openFullChatBtnFirst).toBeVisible({ timeout: 20_000 });
  await openFullChatBtnFirst.click();
  await expect(page).toHaveURL(/\/chat\/[^/?]+/);
  const firstChatId = page.url().match(/\/chat\/([^/?]+)/)?.[1] || "";
  expect(firstChatId).toBeTruthy();

  await page.goto("/pipelines");
  await expect(openDesignBtn).toBeVisible({ timeout: 30_000 });
  const createChatRequestSecond = page.waitForRequest((request) => {
    return request.method() === "POST" && request.url().includes("/api/chats");
  });
  await openDesignBtn.click();
  await createChatRequestSecond;
  const openFullChatBtnSecond = page.getByRole("button", {
    name: /Open Full Chat|完整聊天/i,
  });
  await expect(openFullChatBtnSecond).toBeVisible({ timeout: 20_000 });
  await openFullChatBtnSecond.click();
  await expect(page).toHaveURL(/\/chat\/[^/?]+/);
  const secondChatId = page.url().match(/\/chat\/([^/?]+)/)?.[1] || "";
  expect(secondChatId).toBeTruthy();

  expect(secondChatId).not.toBe(firstChatId);
});

test("behavior: pipeline design entry lands on plain chat url without query params", async ({ page }) => {
  test.setTimeout(90_000);

  await setupApiMocks(page);

  await page.goto("/pipelines");

  const openDesignBtn = page.getByTestId("pipeline-open-design-chat");
  await expect(openDesignBtn).toBeVisible({ timeout: 30_000 });

  const createChatRequest = page.waitForRequest((request) => {
    return request.method() === "POST" && request.url().includes("/api/chats");
  });
  await openDesignBtn.click();
  await createChatRequest;
  const openFullChatBtn = page.getByRole("button", {
    name: /Open Full Chat|完整聊天/i,
  });
  await expect(openFullChatBtn).toBeVisible({ timeout: 20_000 });
  await openFullChatBtn.click();
  await expect(page).toHaveURL(/\/chat\/[^/?]+$/);

  const currentUrl = new URL(page.url());
  expect(currentUrl.pathname).toMatch(/^\/chat\/[^/]+$/);
  expect(currentUrl.search).toBe("");
});

test("behavior: edit pipeline restores bound chat after reload", async ({ page }) => {
  test.setTimeout(90_000);

  await setupApiMocks(page);

  await page.goto("/pipelines");

  const editBtn = page.getByRole("button", {
    name: /Edit Pipeline|编辑流程/i,
  });
  await expect(editBtn).toBeVisible({ timeout: 30_000 });

  const firstCreateRequest = page.waitForRequest((request) => {
    return request.method() === "POST" && request.url().includes("/api/chats");
  });

  await editBtn.click();
  const firstCreate = await firstCreateRequest;
  expect(firstCreate.postDataJSON()).toMatchObject({
    meta: {
      binding_type: "pipeline_edit",
      pipeline_binding_key: "books-alignment-v1@0.1.0",
      pipeline_id: "books-alignment-v1",
      pipeline_version: "0.1.0",
    },
  });

  const exitEditBtn = page.getByRole("button", { name: /Exit Edit|退出编辑/i });
  await expect(exitEditBtn).toBeVisible({ timeout: 20_000 });
  await exitEditBtn.click();

  await page.goto("/pipelines");
  await expect(editBtn).toBeVisible({ timeout: 30_000 });

  let createCount = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/chats")) {
      createCount += 1;
    }
  });

  await editBtn.click();
  await expect(exitEditBtn).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(500);

  expect(createCount).toBe(0);
});

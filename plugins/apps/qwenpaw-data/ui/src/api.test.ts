import { describe, expect, it, vi } from "vitest";

import { createQwenPawDataApi } from "./api";
import type { PawAppSdk, PawRequestOptions } from "./sdk";

describe("QwenPaw-Data semantic API", () => {
  it("loads every CLI semantic resource from the selected datasource", async () => {
    const calls: Array<{ path: string; options?: PawRequestOptions }> = [];
    const get = vi.fn(async (path: string, options?: PawRequestOptions) => {
      calls.push({ path, options });
      if (path.endsWith("/weave-task")) {
        return {
          records: [
            { task_id: "keep", datasource_id: "pg-1", status: "SUCCESS" },
            { task_id: "drop", datasource_id: "pg-2", status: "FAILED" },
          ],
          total: 2,
          page: 1,
          size: 200,
        };
      }
      const name = path.split("/").at(-1);
      return {
        records: [{ id: 1, datasource_id: "pg-1", name }],
        total: 1,
        page: 1,
        size: 200,
      };
    });
    const paw = {
      api: { get },
    } as unknown as PawAppSdk;

    const snapshot = await createQwenPawDataApi(paw).semanticCatalog("pg-1");

    expect(calls).toHaveLength(8);
    expect(calls.map((call) => call.path)).toEqual(
      expect.arrayContaining([
        "/context/semantic-config/biz-domain",
        "/context/semantic-config/dataset-meta",
        "/context/semantic-config/dataset-column-meta",
        "/context/semantic-config/dimension",
        "/context/semantic-config/dataset-dimension",
        "/context/semantic-config/metric-lib",
        "/context/semantic-config/metric-formula-lib",
        "/context/semantic-config/weave-task",
      ]),
    );
    expect(
      calls.find((call) => call.path.endsWith("/metric-lib"))?.options?.query,
    ).toMatchObject({ datasource_id: "pg-1", page: 1, size: 200 });
    expect(
      calls.find((call) => call.path.endsWith("/weave-task"))?.options?.query,
    ).not.toHaveProperty("datasource_id");
    expect(snapshot.totals.metrics).toBe(1);
    expect(snapshot.weave_tasks.map((task) => task.task_id)).toEqual(["keep"]);
  });
});

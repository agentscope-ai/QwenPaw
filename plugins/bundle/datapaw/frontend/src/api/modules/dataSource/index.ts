import { httpDataSourceApi } from "./http";
import { mockDataSourceApi } from "./mock";

/**
 * Toggle HTTP backend vs local mock.
 * Set `VITE_DATA_SOURCE_USE_HTTP=true` in `.env` when backend routes are ready.
 */
const USE_HTTP = import.meta.env.VITE_DATA_SOURCE_USE_HTTP === "true";

export const dataSourceApi = USE_HTTP ? httpDataSourceApi : mockDataSourceApi;

export { mockDataSourceApi, httpDataSourceApi };

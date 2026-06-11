import { httpDataSourceApi } from "./http";
import { mockDataSourceApi } from "./mock";

/**
 * Uses the host `/api/datapaw/data-sources` backend by default.
 * Set `VITE_DATA_SOURCE_USE_MOCK=true` for local mock without a server.
 */
const USE_MOCK = import.meta.env.VITE_DATA_SOURCE_USE_MOCK === "true";

export const dataSourceApi = USE_MOCK ? mockDataSourceApi : httpDataSourceApi;

export { mockDataSourceApi, httpDataSourceApi };

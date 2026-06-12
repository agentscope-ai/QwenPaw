import { SUPPORTED_DATA_SOURCE_TYPES } from "./types";

export function useDataSourceTypes() {
  return {
    types: SUPPORTED_DATA_SOURCE_TYPES,
    loading: false,
    reload: () => {},
  };
}

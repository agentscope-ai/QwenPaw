export interface ModelPoolFilters {
  search: string;
  billing: string;
  capability: string;
  availability: string;
  family: string;
}

export const emptyPoolFilters: ModelPoolFilters = {
  search: "",
  billing: "all",
  capability: "all",
  availability: "all",
  family: "all",
};

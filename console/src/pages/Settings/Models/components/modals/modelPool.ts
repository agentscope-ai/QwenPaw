export interface ModelPoolFilters {
  search: string;
  multimodal: boolean;
  tools: boolean;
  billing: string;
  capability: string;
  availability: string;
  family: string;
}

export const emptyPoolFilters: ModelPoolFilters = {
  search: "",
  multimodal: false,
  tools: false,
  billing: "all",
  capability: "all",
  availability: "all",
  family: "all",
};

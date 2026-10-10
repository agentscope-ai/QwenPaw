export function editable<T extends { id: string; revision: number }>(value: T) {
  return Object.fromEntries(
    Object.entries(value).filter(([key]) => key !== "id" && key !== "revision"),
  ) as Omit<T, "id" | "revision">;
}

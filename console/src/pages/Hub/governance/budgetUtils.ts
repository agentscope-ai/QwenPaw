export type BudgetMode = "inherit" | "limited" | "unlimited" | "blocked";
export function budgetMode(limit: number | null, inherit = false): BudgetMode {
  return inherit
    ? "inherit"
    : limit === null
    ? "unlimited"
    : limit === 0
    ? "blocked"
    : "limited";
}
export function budgetLimit(mode: BudgetMode, amount: number | null) {
  return mode === "limited" ? amount : mode === "blocked" ? 0 : null;
}

export const formatTokens = (value: number, language: string) =>
  new Intl.NumberFormat(language, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);

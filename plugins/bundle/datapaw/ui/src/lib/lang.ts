export function detectLang(): string {
  const stored = localStorage.getItem("language") || "";
  if (stored) return stored.split("-")[0];
  return (navigator.language || "en").split("-")[0];
}

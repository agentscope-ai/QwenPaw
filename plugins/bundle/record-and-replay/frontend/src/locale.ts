import { host } from "./host";
import messages from "./messages.json";

export function useTranslation() {
  const locale = host.useLocale().toLowerCase().split(/[-_]/)[0];
  const selected =
    (messages as Record<string, Record<string, string>>)[locale] ?? messages.en;
  return {
    t: (key: string, values: Record<string, unknown> = {}) => {
      const message =
        selected[key] ?? (messages.en as Record<string, string>)[key] ?? key;
      return message.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
        String(values[name] ?? ""),
      );
    },
  };
}

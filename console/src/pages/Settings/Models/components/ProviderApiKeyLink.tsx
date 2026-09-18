import { Typography } from "antd";
import { useTranslation } from "react-i18next";

/** Optional provider help link, shared by the card and configuration form. */
export function ProviderApiKeyLink({ url }: { url: unknown }) {
  const { t } = useTranslation();
  if (typeof url !== "string") return null;
  try {
    if (!["https:", "http:"].includes(new URL(url).protocol)) return null;
  } catch {
    return null;
  }

  return (
    <Typography.Link
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      style={{ marginInlineStart: 8, textTransform: "none", letterSpacing: 0 }}
      onClick={(event) => event.stopPropagation()}
    >
      {t("models.getApiKey")}
    </Typography.Link>
  );
}

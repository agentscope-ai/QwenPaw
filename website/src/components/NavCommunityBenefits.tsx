import { useTranslation } from "react-i18next";

export const COMMUNITY_BENEFITS_URL =
  "https://opc.aliyun.com/qwenpaw?utm_content=g_1000415374";

export function CommunityBenefitsTriggerLabel({
  className = "",
  badgeAfter = false,
}: {
  className?: string;
  badgeAfter?: boolean;
}) {
  const { t } = useTranslation();

  const badge = (
    <span
      className={
        badgeAfter
          ? "ml-1.5 whitespace-nowrap px-1 py-[3px] text-[9px] font-bold leading-none tracking-wide text-[#181818]"
          : "absolute bottom-full left-1/2 mb-3 -translate-x-1/2 whitespace-nowrap px-1 py-[3px] text-[9px] font-bold leading-none tracking-wide text-[#181818]"
      }
      style={{
        borderRadius: "2.4px",
        background: "linear-gradient(270deg, #f4e5c6 36%, #f6ded3 65%)",
      }}
    >
      {t("nav.communityBenefitsNew")}
    </span>
  );

  return (
    <span className={`inline-flex items-center whitespace-nowrap ${className}`}>
      <span>{t("nav.communityBenefits")}</span>
      {!badgeAfter && (
        <span className="relative inline-flex w-1 shrink-0 justify-center self-center">
          {badge}
        </span>
      )}
      {badgeAfter && badge}
    </span>
  );
}

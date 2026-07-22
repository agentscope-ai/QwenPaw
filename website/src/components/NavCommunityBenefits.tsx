import { ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";

export const COMMUNITY_BENEFITS_URL =
  "https://opc.aliyun.com/qwenpaw?utm_content=g_1000415374";

type BenefitItem = {
  iconSrc: string;
  titleKey: string;
  descKey: string;
};

export const COMMUNITY_BENEFIT_ITEMS: BenefitItem[] = [
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i4/O1CN01cyjRle1Rpn3G7SWPC_!!6000000002161-2-tps-96-96.png",
    titleKey: "nav.benefit1Title",
    descKey: "nav.benefit1Desc",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i3/O1CN010uwdvP27jZXKpjqty_!!6000000007833-2-tps-96-96.png",
    titleKey: "nav.benefit2Title",
    descKey: "nav.benefit2Desc",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i1/O1CN01yioNlX1QKMFpSOn3Z_!!6000000001957-2-tps-96-96.png",
    titleKey: "nav.benefit3Title",
    descKey: "nav.benefit3Desc",
  },
  {
    iconSrc:
      "https://img.alicdn.com/imgextra/i1/O1CN01Z8nE9K1X8B1xv3CtE_!!6000000002878-2-tps-96-96.png",
    titleKey: "nav.benefit4Title",
    descKey: "nav.benefit4Desc",
  },
];

function BenefitIcon({ src }: { src: string }) {
  return (
    <img
      src={src}
      alt=""
      width={36}
      height={36}
      className="size-9 shrink-0 object-contain"
      aria-hidden
    />
  );
}

/** Desktop 2x2 megamenu panel. */
export function CommunityBenefitsPanel({
  onNavigate,
}: {
  onNavigate?: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="grid w-[min(36rem,calc(100vw-2rem))] grid-cols-2 gap-x-0 gap-y-1 p-3">
      {COMMUNITY_BENEFIT_ITEMS.map((item) => (
        <a
          key={item.titleKey}
          href={COMMUNITY_BENEFITS_URL}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onNavigate}
          className="flex gap-3 rounded-lg px-3 py-3 no-underline transition-colors hover:bg-orange-50/70"
        >
          <BenefitIcon src={item.iconSrc} />
          <span className="min-w-0">
            <span className="block text-sm font-semibold leading-snug text-neutral-900">
              {t(item.titleKey)}
            </span>
            <span className="mt-0.5 block text-xs leading-snug text-neutral-500">
              {t(item.descKey)}
            </span>
          </span>
        </a>
      ))}
    </div>
  );
}

/** Mobile accordion list of benefit links. */
export function CommunityBenefitsMobileList({
  onNavigate,
}: {
  onNavigate?: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="mt-1 flex flex-col gap-1 rounded-xs bg-neutral-50 px-2 py-2">
      {COMMUNITY_BENEFIT_ITEMS.map((item) => (
        <a
          key={item.titleKey}
          href={COMMUNITY_BENEFITS_URL}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onNavigate}
          className="flex gap-3 rounded-md px-2 py-2.5 no-underline transition-colors hover:bg-white"
        >
          <BenefitIcon src={item.iconSrc} />
          <span className="min-w-0">
            <span className="block text-sm font-semibold leading-snug text-neutral-900">
              {t(item.titleKey)}
            </span>
            <span className="mt-0.5 block text-xs leading-snug text-neutral-500">
              {t(item.descKey)}
            </span>
          </span>
        </a>
      ))}
    </div>
  );
}

export function CommunityBenefitsTriggerLabel({
  open,
  className = "",
}: {
  open?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();

  return (
    <span className={`inline-flex items-center whitespace-nowrap ${className}`}>
      <span>{t("nav.communityBenefits")}</span>
      <span className="relative inline-flex w-1 shrink-0 justify-center self-center">
        <span
          className="absolute bottom-full left-1/2 mb-3 -translate-x-1/2 whitespace-nowrap px-1 py-[3px] text-[9px] font-bold leading-none tracking-wide text-[#181818]"
          style={{
            borderRadius: "2.4px",
            background: "linear-gradient(270deg, #f4e5c6 36%, #f6ded3 65%)",
          }}
        >
          {t("nav.communityBenefitsNew")}
        </span>
      </span>
      <ChevronDown
        size={14}
        strokeWidth={2}
        aria-hidden
        className={`transition-transform ${open ? "rotate-180" : ""}`}
      />
    </span>
  );
}

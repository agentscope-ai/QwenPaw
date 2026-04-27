import { useState, type ReactNode, useRef } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { QwenpawMascot } from "@/components/QwenpawMascot";
import { GitHubIcon, XIcon, DiscordIcon, WChatIcon } from "./Icon";

const AGENTSCOPE_ORG = "https://github.com/agentscope-ai";
const AGENTSCOPE_REPO = "https://github.com/agentscope-ai/agentscope";
const AGENTSCOPE_RUNTIME =
  "https://github.com/agentscope-ai/agentscope-runtime";
const REME_REPO = "https://github.com/agentscope-ai/ReMe";

interface SocialLink {
  href: string;
  ariaLabel: string;
  icon: ReactNode;
  qrCode?: string;
}

interface PoweredByLink {
  href: string;
  labelKey: string;
}

const socialLinks: SocialLink[] = [
  {
    href: "https://x.com/agentscope_ai",
    ariaLabel: "footer.social.x",
    icon: <XIcon className="block" />,
    qrCode: "https://img.alicdn.com/imgextra/i1/O1CN01sWPF3o1Fp523692rJ_!!6000000000535-2-tps-400-400.png",
  },
  {
    href: "https://github.com/agentscope-ai/QwenPaw",
    ariaLabel: "footer.social.github",
    icon: <GitHubIcon size={20} className="block text-orange-400" />,
    qrCode: "https://img.alicdn.com/imgextra/i1/O1CN014U6Tgn1u8OMZ3rzTo_!!6000000005992-2-tps-400-400.png",
  },
  {
    href: "https://discord.com/invite/eYMpfnkG8h",
    ariaLabel: "footer.social.discord",
    icon: <DiscordIcon className="block" />,
    qrCode:
      "https://img.alicdn.com/imgextra/i2/O1CN0100Yag91yiLuTUd5Gx_!!6000000006612-2-tps-400-400.png",
  },
  {
    href: "https://qr.dingtalk.com/action/joingroup?code=v1,k1,1k7GcVwa5PzZWRaWyBA5OFImW0zNNx1Gj9RkjnuKVGY=&_dt_no_comment=1&origin=1",
    ariaLabel: "footer.social.dingtalk",
    icon: (
      <img
        height={20}
        width={20}
        src="https://img.alicdn.com/imgextra/i1/O1CN01w5mzV01tFtE37wkJI_!!6000000005873-2-tps-48-48.png"
        className="block h-6 w-6"
        style={{
          filter:
            "sepia(100%) hue-rotate(330deg) saturate(300%) brightness(90%)",
        }}
      />
    ),
    qrCode:
      "https://img.alicdn.com/imgextra/i4/O1CN013QPmS61pLbhbhg281_!!6000000005344-2-tps-228-229.png",
  },
  {
    href: "https://www.xiaohongshu.com/user/profile/691c18db0000000037032be9",
    ariaLabel: "footer.social.xiaohongshu",
    icon: (
      <span
        aria-hidden
        className="block text-[18px] leading-none text-orange-400"
      >
        🍠
      </span>
    ),
    qrCode:
      "https://img.alicdn.com/imgextra/i3/O1CN01rNIidF1rpxBc3dOFt_!!6000000005681-2-tps-322-322.png",
  },
  {
    href: "https://mp.weixin.qq.com/s/CE2HkK4XWfmWfuHBQDAZNA",
    ariaLabel: "footer.social.wechat",
    icon: <WChatIcon size={20} className="block" />,
    qrCode:
      "https://img.alicdn.com/imgextra/i4/O1CN01WKxBaC1IgmhnDODyc_!!6000000000923-2-tps-626-628.png",
  },
];

const poweredByLinks: PoweredByLink[] = [
  {
    href: AGENTSCOPE_ORG,
    labelKey: "footer.poweredBy.team",
  },
  {
    href: AGENTSCOPE_REPO,
    labelKey: "footer.poweredBy.agentscope",
  },
  {
    href: AGENTSCOPE_RUNTIME,
    labelKey: "footer.poweredBy.runtime",
  },
  {
    href: REME_REPO,
    labelKey: "footer.poweredBy.reme",
  },
];

export function Footer() {
  const { t } = useTranslation();
  const [hoveredLink, setHoveredLink] = useState<string | null>(null);
  const [qrPosition, setQrPosition] = useState({ top: 0, left: 0 });
  const linkRefs = useRef<Record<string, HTMLAnchorElement | null>>({});

  const linkClass =
    "block text-sm text-[var(--text-muted)] transition-colors hover:!text-(--color-primary)";
  const sectionTitleClass = "text-sm font-semibold text-[var(--text)]";

  const supportsHover = () => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return false;
    }
    return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  };

  const handleMouseEnter = (label: string) => {
    if (!supportsHover()) {
      return;
    }
    setHoveredLink(label);
    const element = linkRefs.current[label];
    if (element) {
      const rect = element.getBoundingClientRect();
      setQrPosition({
        top: rect.top - 180,
        left: rect.left + rect.width / 2,
      });
    }
  };

  const handleMouseLeave = () => {
    setHoveredLink(null);
  };

  const hoveredLinkData = socialLinks.find((l) => l.ariaLabel === hoveredLink);

  return (
    <footer className="mt-auto bg-white">
      <div className="mx-auto max-w-7xl px-6 py-10 md:py-12">
        <div className="flex flex-col gap-10 lg:flex-row lg:items-start lg:justify-between lg:gap-16">
          <section className="min-w-0 max-w-xl">
            <Link to="/" className="inline-flex items-center mb-4">
              <QwenpawMascot size={100} />
            </Link>
            <p className="mb-2 text-[15px] leading-7 text-(--text)">
              {t("whyQwenpaw.heroLine")}
              <br />
              {t("whyQwenpaw.secondPrefix")}
            </p>
            <div className="mt-5 flex items-center gap-4 text-[#f2a25b]">
              {socialLinks.map((link) => (
                <a
                  key={link.ariaLabel}
                  ref={(el) => {
                    if (el) {
                      linkRefs.current[link.ariaLabel] = el;
                    }
                  }}
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={t(link.ariaLabel)}
                  className="relative inline-flex items-center justify-center w-6 h-6 leading-none"
                  onMouseEnter={() => handleMouseEnter(link.ariaLabel)}
                  onMouseLeave={handleMouseLeave}
                >
                  {link.icon}
                </a>
              ))}
            </div>
          </section>

          <section className="shrink-0 lg:ml-auto lg:text-right">
            <div className="space-y-3">
              <h4 className={sectionTitleClass}>
                {t("footer.sections.builtBy")}
              </h4>
              {poweredByLinks.map((link) => (
                <a
                  key={link.labelKey}
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={linkClass}
                >
                  {t(link.labelKey)}
                </a>
              ))}
            </div>
          </section>
        </div>
      </div>

      {hoveredLink && hoveredLinkData?.qrCode &&
        createPortal(
          <div
            className="fixed z-50 pointer-events-none"
            style={{
              top: `${qrPosition.top}px`,
              left: `${qrPosition.left}px`,
              transform: "translateX(-50%)",
            }}
            onMouseEnter={() => setHoveredLink(hoveredLink)}
            onMouseLeave={handleMouseLeave}
          >
            <div className="relative inline-block">
              {/* Content area */}
              <div className="rounded-lg border border-[#f0f0f0] bg-white p-3 shadow-[0_6px_16px_0_rgba(0,0,0,0.08),0_3px_6px_-4px_rgba(0,0,0,0.12),0_9px_28px_8px_rgba(0,0,0,0.05)]">
                <img
                  src={hoveredLinkData.qrCode}
                  alt=""
                  aria-hidden="true"
                  className="block w-35 h-35 rounded"
                />
              </div>
              {/* Bottom arrow */}
              <span
                aria-hidden="true"
                className="absolute left-1/2 top-full h-3 w-3 -translate-x-1/2 -translate-y-1/2 rotate-45 border-r border-b border-[#f0f0f0] bg-white"
              />
            </div>
          </div>,
          document.body
        )}
    </footer>
  );
}

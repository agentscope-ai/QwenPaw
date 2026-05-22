import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Brain,
  Cloud,
  FolderOpen,
  Globe,
  MessageSquare,
  Monitor,
  Plug,
  Search,
  Server,
} from "lucide-react";
import styles from "../components/MCPMarketplaceModal.module.less";

export type MCPMarketIconId =
  | "filesystem"
  | "fetch"
  | "github"
  | "gitlab"
  | "gitee"
  | "postgres"
  | "mysql"
  | "redis"
  | "sqlite"
  | "brave-search"
  | "slack"
  | "yuque"
  | "memory"
  | "aliyun"
  | "aliyun-ack"
  | "aliyun-observability"
  | "remote-http"
  | "puppeteer"
  | "time"
  | "jenkins";

const BRAND = {
  github: "/brand/github.png",
  jenkins: "/brand/jenkins.png",
  aliyun: "/brand/aliyun.png",
  redis: "/brand/redis.png",
  mysql: "/brand/mysql.png",
  gitee: "/brand/gitee.png",
  gitlab: "/brand/gitlab.png",
  yuque: "/brand/yuque.png",
  sqlite: "/brand/sqlite.png",
  postgres: "/brand/postgres.png",
} as const;

/** Brand PNGs are transparent; use a light tile so logos stay visible on cards. */
const BRAND_TILE_BG = "#ffffff";
const BRAND_TILE_BORDER = "1px solid #eae8e7";

function brandImage(src: string, alt: string): IconStyle {
  return {
    imageSrc: src,
    imageAlt: alt,
    bg: BRAND_TILE_BG,
    color: "inherit",
    border: BRAND_TILE_BORDER,
  };
}

interface IconStyle {
  Icon?: LucideIcon;
  label?: string;
  bg: string;
  color: string;
  imageSrc?: string;
  imageAlt?: string;
  border?: string;
  Mark?: (props: { size: number }) => ReactNode;
}

function BrandImageMark({
  src,
  alt,
  size,
}: {
  src: string;
  alt: string;
  size: number;
}) {
  return (
    <img
      src={src}
      alt={alt}
      className={styles.templateIconImg}
      width={size}
      height={size}
      draggable={false}
    />
  );
}

const ICON_STYLES: Record<MCPMarketIconId, IconStyle> = {
  filesystem: { Icon: FolderOpen, bg: "#eef2ff", color: "#4f46e5" },
  fetch: { Icon: Globe, bg: "#e0f2fe", color: "#0284c7" },
  github: brandImage(BRAND.github, "GitHub"),
  gitlab: brandImage(BRAND.gitlab, "GitLab"),
  gitee: brandImage(BRAND.gitee, "Gitee"),
  postgres: brandImage(BRAND.postgres, "PostgreSQL"),
  mysql: brandImage(BRAND.mysql, "MySQL"),
  redis: brandImage(BRAND.redis, "Redis"),
  sqlite: brandImage(BRAND.sqlite, "SQLite"),
  "brave-search": { Icon: Search, bg: "#fef3c7", color: "#d97706" },
  slack: { Icon: MessageSquare, bg: "#f3e8ff", color: "#7c3aed" },
  yuque: brandImage(BRAND.yuque, "Yuque"),
  memory: { Icon: Brain, bg: "#fce7f3", color: "#db2777" },
  aliyun: brandImage(BRAND.aliyun, "Alibaba Cloud"),
  "aliyun-ack": brandImage(BRAND.aliyun, "Alibaba Cloud"),
  "aliyun-observability": brandImage(BRAND.aliyun, "Alibaba Cloud"),
  "remote-http": { Icon: Cloud, bg: "#e0e7ff", color: "#4338ca" },
  puppeteer: { Icon: Monitor, bg: "#f0fdf4", color: "#16a34a" },
  time: { Icon: Server, bg: "#f1f5f9", color: "#475569" },
  jenkins: brandImage(BRAND.jenkins, "Jenkins"),
};

interface MCPTemplateIconProps {
  iconId: MCPMarketIconId;
  size?: "sm" | "md";
}

/** Fallback icon for custom (non-market) MCP clients. */
export function MCPCustomClientIcon({ size = "md" }: { size?: "sm" | "md" }) {
  const dim = size === "sm" ? 32 : 40;
  const iconSize = size === "sm" ? 16 : 20;
  return (
    <span
      className={styles.templateIconBadge}
      style={{
        width: dim,
        height: dim,
        backgroundColor: "#f1f5f9",
        color: "#64748b",
      }}
      aria-hidden
    >
      <Plug size={iconSize} strokeWidth={2} />
    </span>
  );
}

export function MCPTemplateIcon({ iconId, size = "md" }: MCPTemplateIconProps) {
  const style = ICON_STYLES[iconId] ?? ICON_STYLES.aliyun;
  const dim = size === "sm" ? 32 : 40;
  const iconSize = size === "sm" ? 16 : 20;
  const LucideIcon = style.Icon;
  const Mark = style.Mark;
  const useBrandImage = !!style.imageSrc;

  return (
    <span
      className={`${styles.templateIconBadge}${
        useBrandImage ? ` ${styles.templateIconBrand}` : ""
      }`}
      style={{
        width: dim,
        height: dim,
        backgroundColor: style.bg,
        color: style.color,
        border: style.border,
        padding: useBrandImage ? 3 : undefined,
        overflow: "hidden",
      }}
      aria-hidden={useBrandImage ? undefined : true}
      title={style.imageAlt}
    >
      {useBrandImage ? (
        <BrandImageMark
          src={style.imageSrc!}
          alt={style.imageAlt ?? iconId}
          size={dim}
        />
      ) : Mark ? (
        <Mark size={dim} />
      ) : style.label ? (
        <span className={styles.templateIconLabel}>{style.label}</span>
      ) : LucideIcon ? (
        <LucideIcon size={iconSize} strokeWidth={2} />
      ) : null}
    </span>
  );
}

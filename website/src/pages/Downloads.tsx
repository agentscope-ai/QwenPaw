import { useEffect, useState } from "react";
import { type Lang } from "../i18n";
import { type SiteConfig } from "../config";
import { Nav } from "../components/Nav";
import { Footer } from "../components/Footer";
import "../styles/downloads.css";

interface FileMetadata {
  id: string;
  name: { "zh-CN": string; "en-US": string };
  description: { "zh-CN": string; "en-US": string };
  product: string;
  platform: string;
  version: string;
  filename: string;
  url: string;
  size: string;
  size_bytes: number;
  sha256: string;
  updated_at: string;
  type: string;
}

interface PlatformData {
  latest: string;
  versions: string[];
}

interface DesktopIndex {
  product: string;
  updated_at: string;
  platforms: Record<string, PlatformData>;
  files: Record<string, FileMetadata>;
}

interface MainIndex {
  version: string;
  updated_at: string;
  products: Record<
    string,
    {
      name: { "zh-CN": string; "en-US": string };
      index_url: string;
    }
  >;
}

const platformIcons: Record<string, string> = {
  win: "🪟",
  mac: "🍎",
  linux: "🐧",
};

function detectOS(): string | null {
  const userAgent = window.navigator.userAgent.toLowerCase();
  if (userAgent.indexOf("win") !== -1) return "win";
  if (userAgent.indexOf("mac") !== -1) return "mac";
  if (userAgent.indexOf("linux") !== -1) return "linux";
  return null;
}

interface PlatformCardProps {
  fileMetadata: FileMetadata;
  isRecommended: boolean;
  lang: Lang;
}

function PlatformCard({
  fileMetadata,
  isRecommended,
  lang,
}: PlatformCardProps) {
  const platformName =
    lang === "zh" ? fileMetadata.name["zh-CN"] : fileMetadata.name["en-US"];
  const description =
    lang === "zh"
      ? fileMetadata.description["zh-CN"]
      : fileMetadata.description["en-US"];
  const icon = platformIcons[fileMetadata.platform] || "📦";
  const updatedDate = new Date(fileMetadata.updated_at).toLocaleDateString(
    lang === "zh" ? "zh-CN" : "en-US",
  );
  const downloadUrl = `https://download.copaw.agentscope.io${fileMetadata.url}`;

  return (
    <div className="platform-card">
      <div className="platform-header">
        <div className="platform-icon">{icon}</div>
        <div className="platform-info">
          <h4>
            {platformName}
            {isRecommended && (
              <span className="recommended-badge">
                {lang === "zh" ? "推荐" : "Recommended"}
              </span>
            )}
          </h4>
          <div className="platform-version">v{fileMetadata.version}</div>
        </div>
      </div>
      <p className="platform-description">{description}</p>
      <a
        href={downloadUrl}
        className={`download-btn ${isRecommended ? "recommended" : ""}`}
        download
      >
        {lang === "zh" ? "下载" : "Download"}
      </a>
      <div className="file-details">
        <div className="detail-row">
          <span className="detail-label">
            {lang === "zh" ? "版本" : "Version"}:
          </span>
          <span>{fileMetadata.version}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">
            {lang === "zh" ? "大小" : "Size"}:
          </span>
          <span>{fileMetadata.size}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">
            {lang === "zh" ? "更新时间" : "Updated"}:
          </span>
          <span>{updatedDate}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">SHA256:</span>
        </div>
        <div className="sha256">{fileMetadata.sha256}</div>
      </div>
    </div>
  );
}

interface DownloadsProps {
  config: SiteConfig;
  lang: Lang;
  onLangClick: () => void;
}

export function Downloads({ config, lang, onLangClick }: DownloadsProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [desktopIndex, setDesktopIndex] = useState<DesktopIndex | null>(null);
  const userOS = detectOS();

  useEffect(() => {
    async function loadDownloads() {
      try {
        const CDN_BASE = "https://download.copaw.agentscope.io";

        const mainIndexResponse = await fetch(
          `${CDN_BASE}/metadata/index.json`,
        );
        if (!mainIndexResponse.ok) {
          throw new Error("Failed to fetch main index");
        }
        const mainIndex: MainIndex = await mainIndexResponse.json();

        if (mainIndex.products.desktop) {
          const desktopIndexResponse = await fetch(
            `${CDN_BASE}${mainIndex.products.desktop.index_url}`,
          );
          if (!desktopIndexResponse.ok) {
            throw new Error("Failed to fetch desktop index");
          }
          const desktopData: DesktopIndex = await desktopIndexResponse.json();
          setDesktopIndex(desktopData);
        }

        setLoading(false);
      } catch (err) {
        console.error("Error loading downloads:", err);
        setError(true);
        setLoading(false);
      }
    }

    loadDownloads();
  }, []);

  return (
    <div className="downloads-page">
      <Nav
        projectName={config.projectName}
        lang={lang}
        onLangClick={onLangClick}
        docsPath={config.docsPath}
        repoUrl={config.repoUrl}
      />

      <div className="downloads-container">
        <header className="downloads-header">
          <h1>{lang === "zh" ? "下载 CoPaw" : "Download CoPaw"}</h1>
          <p className="subtitle">
            {lang === "zh"
              ? "选择您的平台并开始使用"
              : "Choose your platform and get started"}
          </p>
        </header>

        {loading && (
          <div className="loading">
            <div className="spinner"></div>
            <p>{lang === "zh" ? "加载中..." : "Loading..."}</p>
          </div>
        )}

        {error && (
          <div className="error">
            <p>
              {lang === "zh"
                ? "加载下载信息失败，请稍后重试。"
                : "Failed to load download information. Please try again later."}
            </p>
          </div>
        )}

        {!loading && !error && desktopIndex && (
          <section className="downloads-section">
            <div className="product-section">
              <h3 className="product-title">
                {lang === "zh" ? "桌面客户端" : "Desktop Client"}
              </h3>
              <div className="platform-grid">
                {Object.entries(desktopIndex.platforms).map(
                  ([platform, platformData]) => {
                    const latestFileId = platformData.latest;
                    const fileMetadata = desktopIndex.files[latestFileId];

                    if (!fileMetadata) return null;

                    const isRecommended = platform === userOS;
                    return (
                      <PlatformCard
                        key={platform}
                        fileMetadata={fileMetadata}
                        isRecommended={isRecommended}
                        lang={lang}
                      />
                    );
                  },
                )}
              </div>
            </div>

            <section className="info-section">
              <div className="info-card">
                <h4>{lang === "zh" ? "验证下载" : "Verify Download"}</h4>
                <p>
                  {lang === "zh"
                    ? "下载后，请使用每个下载按钮下方显示的 SHA256 校验和验证文件完整性。"
                    : "After downloading, verify the file integrity using the SHA256 checksum displayed below each download button."}
                </p>
              </div>
              <div className="info-card">
                <h4>{lang === "zh" ? "安装说明" : "Installation"}</h4>
                <p>
                  {lang === "zh"
                    ? "按照您平台的安装向导进行操作。详细说明请访问我们的文档。"
                    : "Follow the installation wizard for your platform. For detailed instructions, visit our documentation."}
                </p>
              </div>
            </section>
          </section>
        )}
      </div>

      <Footer lang={lang} />
    </div>
  );
}

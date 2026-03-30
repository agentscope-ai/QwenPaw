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
  const [isEmpty, setIsEmpty] = useState(false);
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
          if (mainIndexResponse.status === 404) {
            setIsEmpty(true);
            setLoading(false);
            return;
          }
          throw new Error("Failed to fetch main index");
        }
        const mainIndex: MainIndex = await mainIndexResponse.json();

        if (mainIndex.products.desktop) {
          const desktopIndexResponse = await fetch(
            `${CDN_BASE}${mainIndex.products.desktop.index_url}`,
          );
          if (desktopIndexResponse.ok) {
            const desktopData: DesktopIndex = await desktopIndexResponse.json();
            setDesktopIndex(desktopData);
          }
        }

        if (!mainIndex.products.desktop) {
          setIsEmpty(true);
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
          <h1>{lang === "zh" ? "下载资源" : "Downloads"}</h1>
          <p className="subtitle">
            {lang === "zh"
              ? "获取 CoPaw 的各种安装包和工具"
              : "Get CoPaw installers, tools, and resources"}
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

        {isEmpty && !loading && !error && (
          <div className="empty-state">
            <div className="empty-icon">📦</div>
            <h3>
              {lang === "zh" ? "暂无可下载内容" : "No downloads available yet"}
            </h3>
            <p>
              {lang === "zh"
                ? "桌面应用正在构建中，请稍后再来查看。"
                : "Desktop builds are in progress. Please check back later."}
            </p>
            <a href={`${config.docsPath}/quickstart`} className="empty-cta">
              {lang === "zh"
                ? "查看其他安装方式"
                : "View other installation methods"}
            </a>
          </div>
        )}

        {!loading && !error && !isEmpty && (
          <section className="downloads-section">
            {desktopIndex && (
              <div className="product-section">
                <div className="product-header">
                  <h3 className="product-title">
                    {lang === "zh" ? "桌面应用" : "Desktop Application"}
                  </h3>
                  <p className="product-description">
                    {lang === "zh"
                      ? "独立打包的桌面应用，内置完整 Python 环境和所有依赖。双击即用，无需命令行。"
                      : "Standalone desktop app with bundled Python environment and all dependencies. Double-click to run, no command line required."}
                  </p>
                </div>
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
            )}

            <div className="product-section">
              <div className="product-header">
                <h3 className="product-title">
                  {lang === "zh"
                    ? "其他安装方式"
                    : "Other Installation Methods"}
                </h3>
                <p className="product-description">
                  {lang === "zh"
                    ? "根据您的需求选择合适的安装方式"
                    : "Choose the installation method that fits your needs"}
                </p>
              </div>
              <div className="other-methods">
                <a
                  href={`${config.docsPath}/quickstart`}
                  className="method-card"
                >
                  <div className="method-icon">📦</div>
                  <h4>pip</h4>
                  <p>
                    {lang === "zh"
                      ? "使用 pip 安装到现有 Python 环境"
                      : "Install via pip to existing Python environment"}
                  </p>
                </a>
                <a
                  href={`${config.docsPath}/quickstart`}
                  className="method-card"
                >
                  <div className="method-icon">📜</div>
                  <h4>{lang === "zh" ? "脚本安装" : "Script"}</h4>
                  <p>
                    {lang === "zh"
                      ? "一键安装脚本，自动配置环境"
                      : "One-line script with automatic setup"}
                  </p>
                </a>
                <a
                  href={`${config.docsPath}/quickstart`}
                  className="method-card"
                >
                  <div className="method-icon">🐳</div>
                  <h4>Docker</h4>
                  <p>
                    {lang === "zh"
                      ? "使用 Docker 镜像快速部署"
                      : "Quick deployment with Docker images"}
                  </p>
                </a>
                <a
                  href={`${config.docsPath}/quickstart`}
                  className="method-card"
                >
                  <div className="method-icon">☁️</div>
                  <h4>{lang === "zh" ? "云部署" : "Cloud"}</h4>
                  <p>
                    {lang === "zh"
                      ? "阿里云、魔搭等云平台一键部署"
                      : "Deploy on Aliyun, ModelScope, etc."}
                  </p>
                </a>
              </div>
            </div>

            <section className="info-section">
              <div className="info-card">
                <h4>{lang === "zh" ? "验证下载" : "Verify Download"}</h4>
                <p>
                  {lang === "zh"
                    ? "下载桌面应用后，请使用 SHA256 校验和验证文件完整性。"
                    : "After downloading the desktop app, verify file integrity using the SHA256 checksum."}
                </p>
              </div>
              <div className="info-card">
                <h4>{lang === "zh" ? "需要帮助？" : "Need Help?"}</h4>
                <p>
                  {lang === "zh" ? (
                    <>
                      查看{" "}
                      <a href={`${config.docsPath}/quickstart`}>安装向导</a>{" "}
                      了解详细的安装步骤和配置说明。
                    </>
                  ) : (
                    <>
                      See the{" "}
                      <a href={`${config.docsPath}/quickstart`}>
                        installation guide
                      </a>{" "}
                      for detailed setup instructions.
                    </>
                  )}
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

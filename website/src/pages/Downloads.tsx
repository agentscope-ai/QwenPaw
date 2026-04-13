import { useEffect, useState } from "react";
import { Download, Monitor, Laptop } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useSiteConfig } from "@/config-context";
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

const platformIcons: Record<string, typeof Monitor> = {
  win: Monitor,
  mac: Laptop,
  linux: Monitor,
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
  allVersions: string[];
  isRecommended: boolean;
}

function PlatformCard({
  fileMetadata,
  allVersions,
  isRecommended,
}: PlatformCardProps) {
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";
  const [selectedVersion, setSelectedVersion] = useState(fileMetadata.version);

  const platformName = isZh
    ? fileMetadata.name["zh-CN"]
    : fileMetadata.name["en-US"];
  const description = isZh
    ? fileMetadata.description["zh-CN"]
    : fileMetadata.description["en-US"];
  const IconComponent = platformIcons[fileMetadata.platform] || Monitor;
  const updatedDate = new Date(fileMetadata.updated_at).toLocaleDateString(
    isZh ? "zh-CN" : "en-US",
  );
  const downloadUrl = `https://download.qwenpaw.agentscope.io${fileMetadata.url}`;

  return (
    <div className={`platform-card ${isRecommended ? "recommended" : ""}`}>
      <div className="platform-header">
        <div className="platform-icon">
          <IconComponent size={28} strokeWidth={2} />
        </div>
        <div className="platform-info">
          <h4>
            {platformName}
            {isRecommended && (
              <span className="recommended-badge">
                {t("downloads.recommended")}
              </span>
            )}
          </h4>
          <div className="platform-version">v{fileMetadata.version}</div>
        </div>
      </div>
      <p className="platform-description">{description}</p>

      {allVersions.length > 1 && (
        <div className="version-selector">
          <label className="version-label">
            {t("downloads.selectVersion")}
          </label>
          <select
            className="version-dropdown"
            value={selectedVersion}
            onChange={(e) => setSelectedVersion(e.target.value)}
          >
            {allVersions.map((version, index) => (
              <option key={version} value={version}>
                v{version} {index === 0 ? `(${t("downloads.latest")})` : ""}
              </option>
            ))}
          </select>
        </div>
      )}

      <a href={downloadUrl} className="download-btn" download>
        <Download size={18} strokeWidth={2.5} />
        {t("downloads.download")}
      </a>

      <div className="file-details">
        <div className="detail-row">
          <span className="detail-label">{t("downloads.version")}:</span>
          <span>{fileMetadata.version}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">{t("downloads.size")}:</span>
          <span>{fileMetadata.size}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">{t("downloads.updated")}:</span>
          <span>{updatedDate}</span>
        </div>
        <div className="sha256-row">
          <span className="detail-label">SHA256:</span>
          <div className="sha256">{fileMetadata.sha256}</div>
        </div>
      </div>
    </div>
  );
}

export default function Downloads() {
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";
  const { docsPath } = useSiteConfig();
  const [loading, setLoading] = useState(true);
  const [isEmpty, setIsEmpty] = useState(false);
  const [desktopIndex, setDesktopIndex] = useState<DesktopIndex | null>(null);
  const userOS = detectOS();
  const docsBase = docsPath.replace(/\/$/, "") || "/docs";

  useEffect(() => {
    async function loadDownloads() {
      try {
        const CDN_BASE = "https://download.qwenpaw.agentscope.io";

        console.log(
          "Fetching main index from:",
          `${CDN_BASE}/metadata/index.json`,
        );
        const mainIndexResponse = await fetch(
          `${CDN_BASE}/metadata/index.json`,
        );

        console.log("Main index response status:", mainIndexResponse.status);

        if (!mainIndexResponse.ok) {
          if (mainIndexResponse.status === 404) {
            console.warn("Main index not found (404)");
            setIsEmpty(true);
            setLoading(false);
            return;
          }
          throw new Error("Failed to fetch main index");
        }

        const mainIndex: MainIndex = await mainIndexResponse.json();
        console.log("Main index data:", mainIndex);

        let hasDesktopData = false;

        if (mainIndex.products?.desktop) {
          const desktopIndexUrl = `${CDN_BASE}${mainIndex.products.desktop.index_url}`;
          console.log("Fetching desktop index from:", desktopIndexUrl);

          const desktopIndexResponse = await fetch(desktopIndexUrl);
          console.log(
            "Desktop index response status:",
            desktopIndexResponse.status,
          );

          if (desktopIndexResponse.ok) {
            const desktopData: DesktopIndex = await desktopIndexResponse.json();
            console.log("Desktop index data:", desktopData);
            setDesktopIndex(desktopData);
            hasDesktopData = true;
          } else {
            console.warn(
              "Desktop index fetch failed with status:",
              desktopIndexResponse.status,
            );
          }
        } else {
          console.warn("No desktop product found in main index");
        }

        if (!hasDesktopData) {
          console.warn("No desktop data available, showing empty state");
          setIsEmpty(true);
        }

        setLoading(false);
      } catch (err) {
        console.error("Error loading downloads:", err);
        setIsEmpty(true);
        setLoading(false);
      }
    }

    loadDownloads();
  }, []);

  return (
    <div className="downloads-page">
      <div className="downloads-container">
        <header className="downloads-header">
          <h1>{t("downloads.title")}</h1>
          <p className="subtitle">{t("downloads.subtitle")}</p>
        </header>

        {loading && (
          <div className="loading">
            <div className="spinner"></div>
            <p>{t("downloads.loading")}</p>
          </div>
        )}

        {isEmpty && !loading && (
          <div className="empty-state">
            <div className="empty-icon">📦</div>
            <h3>{t("downloads.emptyTitle")}</h3>
            <p>{t("downloads.emptyDesc")}</p>
            <Link to={`${docsBase}/quickstart`} className="empty-cta">
              {t("downloads.emptyCta")}
            </Link>
          </div>
        )}

        {!loading && !isEmpty && (
          <section className="downloads-section">
            {desktopIndex && (
              <div className="product-section">
                <div className="product-header">
                  <h3 className="product-title">
                    {t("downloads.desktopTitle")}
                  </h3>
                  <p className="product-description">
                    {t("downloads.desktopDesc")}
                  </p>
                </div>
                <div className="platform-grid">
                  {Object.entries(desktopIndex.platforms).map(
                    ([platform, platformData]) => {
                      const latestFileId = platformData.latest;
                      const fileMetadata = desktopIndex.files[latestFileId];

                      if (!fileMetadata) return null;

                      const isRecommended = platform === userOS;
                      const allVersions = platformData.versions || [
                        fileMetadata.version,
                      ];

                      return (
                        <PlatformCard
                          key={platform}
                          fileMetadata={fileMetadata}
                          allVersions={allVersions}
                          isRecommended={isRecommended}
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
                  {t("downloads.otherMethodsTitle")}
                </h3>
                <p className="product-description">
                  {t("downloads.otherMethodsDesc")}
                </p>
              </div>
              <div className="other-methods">
                <Link
                  to={`${docsBase}/quickstart#${
                    isZh ? "方式一pip-安装" : "Option-1-pip-install"
                  }`}
                  className="method-card"
                >
                  <div className="method-icon">📦</div>
                  <h4>{t("downloads.pip")}</h4>
                  <p>{t("downloads.pipDesc")}</p>
                </Link>
                <Link
                  to={`${docsBase}/quickstart#${
                    isZh ? "方式二脚本安装" : "Option-2-Script-install"
                  }`}
                  className="method-card"
                >
                  <div className="method-icon">📜</div>
                  <h4>{t("downloads.script")}</h4>
                  <p>{t("downloads.scriptDesc")}</p>
                </Link>
                <Link
                  to={`${docsBase}/quickstart#${
                    isZh ? "方式三Docker" : "Option-3-Docker"
                  }`}
                  className="method-card"
                >
                  <div className="method-icon">🐳</div>
                  <h4>{t("downloads.docker")}</h4>
                  <p>{t("downloads.dockerDesc")}</p>
                </Link>
                <Link
                  to={`${docsBase}/quickstart#${
                    isZh
                      ? "方式四部署到阿里云-ECS"
                      : "Option-4-Deploy-to-Alibaba-Cloud-ECS"
                  }`}
                  className="method-card"
                >
                  <div className="method-icon">☁️</div>
                  <h4>{t("downloads.cloud")}</h4>
                  <p>{t("downloads.cloudDesc")}</p>
                </Link>
              </div>
            </div>

            <section className="info-section">
              <div className="info-card">
                <h4>{t("downloads.verifyTitle")}</h4>
                <p>{t("downloads.verifyDesc")}</p>
              </div>
              <div className="info-card">
                <h4>{t("downloads.helpTitle")}</h4>
                <p>
                  {t("downloads.helpPrefix")}{" "}
                  <Link to={`${docsBase}/quickstart`}>
                    {t("downloads.helpLink")}
                  </Link>{" "}
                  {t("downloads.helpSuffix")}
                </p>
              </div>
            </section>
          </section>
        )}
      </div>
    </div>
  );
}

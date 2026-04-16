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
  versions: FileMetadata[];
  latestStableFileId: string | null;
  isRecommended: boolean;
}

function PlatformCard({
  versions,
  latestStableFileId,
  isRecommended,
}: PlatformCardProps) {
  const { t, i18n } = useTranslation();
  const isZh = i18n.resolvedLanguage === "zh";
  const [selectedFileId, setSelectedFileId] = useState(versions[0]?.id ?? "");

  const selectedFileMetadata =
    versions.find((item) => item.id === selectedFileId) ?? versions[0];

  if (!selectedFileMetadata) {
    return null;
  }

  const platformName = isZh
    ? selectedFileMetadata.name["zh-CN"]
    : selectedFileMetadata.name["en-US"];
  const description = isZh
    ? selectedFileMetadata.description["zh-CN"]
    : selectedFileMetadata.description["en-US"];
  const IconComponent = platformIcons[selectedFileMetadata.platform] || Monitor;
  const updatedDate = new Date(
    selectedFileMetadata.updated_at,
  ).toLocaleDateString(isZh ? "zh-CN" : "en-US");
  const downloadUrl = `https://download.qwenpaw.agentscope.io${selectedFileMetadata.url}`;
  const stableVersions = versions.filter(
    (item) => !/[ab]\d*$/i.test(item.version) && !/preview/i.test(item.version),
  );
  const previewVersions = versions.filter(
    (item) => /[ab]\d*$/i.test(item.version) || /preview/i.test(item.version),
  );

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
          <div className="platform-version">
            v{selectedFileMetadata.version}
          </div>
        </div>
      </div>
      <p className="platform-description">{description}</p>

      {versions.length > 1 && (
        <div className="version-selector">
          <label className="version-label">
            {t("downloads.selectVersion")}
          </label>
          <select
            className="version-dropdown"
            value={selectedFileId}
            onChange={(e) => setSelectedFileId(e.target.value)}
          >
            {stableVersions.length > 0 &&
              stableVersions.map((versionItem) => (
                <option key={versionItem.id} value={versionItem.id}>
                  v{versionItem.id}
                  {latestStableFileId === versionItem.id
                    ? ` (${t("downloads.latest")})`
                    : ""}
                </option>
              ))}
            {previewVersions.length > 0 && (
              <optgroup label="Preview">
                {previewVersions.map((versionItem) => (
                  <option key={versionItem.id} value={versionItem.id}>
                    v{versionItem.id}
                  </option>
                ))}
              </optgroup>
            )}
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
          <span>{selectedFileMetadata.version}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">{t("downloads.size")}:</span>
          <span>{selectedFileMetadata.size}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">{t("downloads.updated")}:</span>
          <span>{updatedDate}</span>
        </div>
        <div className="sha256-row">
          <span className="detail-label">SHA256:</span>
          <div className="sha256">{selectedFileMetadata.sha256}</div>
        </div>
      </div>
    </div>
  );
}

function isPreviewVersion(version: string): boolean {
  return /[ab]\d*$/i.test(version) || /preview/i.test(version);
}

function compareVersionPart(a: string, b: string): number {
  const aNum = Number(a);
  const bNum = Number(b);

  if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) {
    return aNum - bNum;
  }

  return a.localeCompare(b);
}

function compareVersionDesc(a: string, b: string): number {
  const aBase = a.match(/^\d+(?:\.\d+)*/)?.[0] ?? "0";
  const bBase = b.match(/^\d+(?:\.\d+)*/)?.[0] ?? "0";
  const aParts = aBase.split(".");
  const bParts = bBase.split(".");
  const maxLength = Math.max(aParts.length, bParts.length);

  for (let i = 0; i < maxLength; i += 1) {
    const result = compareVersionPart(aParts[i] ?? "0", bParts[i] ?? "0");
    if (result !== 0) {
      return -result;
    }
  }

  const aIsPreview = isPreviewVersion(a);
  const bIsPreview = isPreviewVersion(b);
  if (aIsPreview !== bIsPreview) {
    return aIsPreview ? 1 : -1;
  }

  return b.localeCompare(a);
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
                      const platformVersions = (platformData.versions || [])
                        .map((fileId) => desktopIndex.files[fileId])
                        .filter((item): item is FileMetadata => Boolean(item))
                        .sort((a, b) =>
                          compareVersionDesc(a.version, b.version),
                        );

                      if (platformVersions.length === 0) return null;

                      const latestStable = platformVersions.find(
                        (item) => !isPreviewVersion(item.version),
                      );
                      const defaultVersion =
                        latestStable ?? platformVersions[0];
                      const isRecommended = platform === userOS;

                      return (
                        <PlatformCard
                          key={platform}
                          versions={[
                            defaultVersion,
                            ...platformVersions.filter(
                              (item) => item.id !== defaultVersion.id,
                            ),
                          ]}
                          latestStableFileId={latestStable?.id ?? null}
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

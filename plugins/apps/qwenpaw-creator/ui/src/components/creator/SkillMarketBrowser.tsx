import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Modal, Spin, message, type InputRef } from "antd";
import {
  Download,
  Globe,
  Search,
  User,
  AppWindow,
  ShoppingBag,
} from "lucide-react";
import {
  importSkillFromUrl,
  listMarketProviders,
  searchMarketSkills,
  type MarketProvider,
  type MarketSkillResult,
} from "@/api/creator";

/** Market source label lookup for display purposes. */
const KNOWN_SOURCES: Record<string, string> = {
  qwenpaw: "QwenPaw",
  "skills-sh": "Skills.sh",
  github: "GitHub",
  clawhub: "ClawHub",
  lobehub: "LobeHub",
  modelscope: "ModelScope",
  aliyun: "Aliyun",
  skillsmp: "SkillsMP",
};

function sourceLabel(source: string, label: string | null): string {
  return label || KNOWN_SOURCES[source] || source;
}

/** Identity of one result row, the same key the list renders by. */
function rowKey(item: MarketSkillResult): string {
  return `${item.source}-${item.slug}`;
}

/**
 * Where a row's install identity is remembered. React state dies with the
 * pane: settings renders ``{activePane === "skills" && <SkillsConfigPane />}``,
 * so switching panes rebuilds this component and would forget which name a
 * renamed row installed. Browser storage is scoped to the origin, and one
 * origin is one running Creator instance.
 *
 * The memory is inert on its own: a row only counts as installed while the
 * name it remembers is still in the library, so a deleted skill frees its row
 * again and nothing has to prune this map.
 */
const ROW_MEMORY_KEY = "qwenpaw.creator.skillMarket.installedRows";

function readRowMemory(): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(ROW_MEMORY_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const memory: Record<string, string> = {};
    for (const [key, value] of Object.entries(parsed)) {
      if (typeof value === "string") memory[key] = value;
    }
    return memory;
  } catch {
    // Disabled, unparsable or blocked storage degrades to "nothing
    // remembered"; it must never turn into a failed install.
    return {};
  }
}

function writeRowMemory(memory: Record<string, string>): void {
  try {
    window.localStorage.setItem(ROW_MEMORY_KEY, JSON.stringify(memory));
  } catch {
    // Same here: this opening still works, only the next one forgets.
  }
}

interface SkillMarketBrowserProps {
  open: boolean;
  onClose: () => void;
  /** Called after a successful install so the pane can refresh its list. */
  onInstalled: () => void;
  /** Currently installed skill names, for disabling already-installed items. */
  installedNames: string[];
}

export default function SkillMarketBrowser({
  open,
  onClose,
  onInstalled,
  installedNames,
}: SkillMarketBrowserProps) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language || "en";
  const [query, setQuery] = useState("");
  /**
   * The search term the rendered results actually belong to. ``query`` is only
   * an input draft; paging must never pick it up, or page 2 of an unsubmitted
   * term would be appended to another term's results.
   */
  const [committedQuery, setCommittedQuery] = useState("");
  const [results, setResults] = useState<MarketSkillResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  const [installing, setInstalling] = useState<Set<string>>(new Set());
  /** Skills this session installed, on top of the pane's library. */
  const [localInstalled, setLocalInstalled] = useState<Set<string>>(new Set());
  /**
   * Row identity to the name that was really installed, restored from browser
   * storage because the pane can be torn down between openings. A folded
   * install name never matches the market row's label, so this is the only
   * thing that can tell the two apart.
   */
  const [rowInstallNames, setRowInstallNames] =
    useState<Record<string, string>>(readRowMemory);
  const [providers, setProviders] = useState<MarketProvider[]>([]);
  const searchSeqRef = useRef(0);
  const resultsRef = useRef<MarketSkillResult[]>([]);
  const inputRef = useRef<InputRef>(null);
  // Synchronous mirror of ``rowInstallNames``: installing is the only writer,
  // and writing storage inside a state updater would repeat under StrictMode
  // replays the way a request side effect would.
  const rowInstallNamesRef = useRef<Record<string, string>>(rowInstallNames);
  // Synchronous guard so rapid double-clicks cannot pass the installing
  // check before React commits the first setInstalling update.
  const installingRef = useRef<Set<string>>(new Set());

  // Focus search input when modal opens.
  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => inputRef.current?.focus(), 100);
    return () => clearTimeout(timer);
  }, [open]);

  // Derived instead of mirrored: the pane owns the library and this session
  // only adds what it just installed, so there is no render where the two
  // disagree (a synced state would be one effect behind).
  const installed = useMemo(
    () => new Set([...installedNames, ...localInstalled]),
    [installedNames, localInstalled],
  );

  // Which markets the runtime can actually reach. Without this, a browse that
  // fails because a provider is unconfigured looks like an empty market.
  useEffect(() => {
    if (!open) return;
    let discarded = false;
    listMarketProviders()
      .then((res) => {
        if (!discarded) setProviders(res.providers);
      })
      .catch(() => {
        if (!discarded) message.error(t("skills.marketLoadFailed"));
      });
    return () => {
      discarded = true;
    };
  }, [open, t]);

  const unavailableProviders = useMemo(
    () => providers.filter((provider) => !provider.available),
    [providers],
  );

  const isRowInstalled = useCallback(
    (item: MarketSkillResult) => {
      if (installed.has(item.name)) return true;
      const installedAs = rowInstallNames[rowKey(item)];
      return installedAs !== undefined && installed.has(installedAs);
    },
    [installed, rowInstallNames],
  );

  const doSearch = useCallback(
    async (searchQuery: string, searchPage: number) => {
      const seq = searchSeqRef.current + 1;
      searchSeqRef.current = seq;
      setLoading(true);
      try {
        const res = await searchMarketSkills(searchQuery, searchPage, 20, lang);
        if (seq !== searchSeqRef.current) return;
        const accumulated =
          searchPage === 1
            ? res.results
            : [...resultsRef.current, ...res.results];
        resultsRef.current = accumulated;
        setResults(accumulated);
        setHasMore(res.has_more);
        setSearched(true);
        // Both the page and the term advance only once a response arrived, so
        // a failed request leaves them at the last good value and the next
        // click retries the page that failed instead of skipping it.
        setPage(searchPage);
        setCommittedQuery(searchQuery);
      } catch (error) {
        if (seq !== searchSeqRef.current) return;
        // The host says what to do in the detail: a 501 explains that this
        // runtime has no market service and points at URL import, a 502 names
        // the failing provider. Swallowing it leaves a dead end.
        message.error(
          error instanceof Error && error.message
            ? error.message
            : t("skills.marketSearchFailed"),
        );
      } finally {
        if (seq === searchSeqRef.current) {
          setLoading(false);
        }
      }
    },
    [lang, t],
  );

  const handleSearch = useCallback(() => {
    void doSearch(query, 1);
  }, [query, doSearch]);

  const handleLoadMore = useCallback(() => {
    void doSearch(committedQuery, page + 1);
  }, [committedQuery, page, doSearch]);

  const handleInstall = useCallback(
    async (item: MarketSkillResult) => {
      if (installingRef.current.has(item.slug) || isRowInstalled(item)) return;
      installingRef.current = new Set(installingRef.current).add(item.slug);
      setInstalling((prev) => new Set(prev).add(item.slug));
      try {
        const res = await importSkillFromUrl(item.source_url);
        // A market name that is not a valid slug gets folded by the backend,
        // so the overlay, the toast and the rename notice must speak about the
        // name that was really installed rather than the row's label.
        setLocalInstalled((prev) => new Set(prev).add(res.name));
        // One write path, outside the updater, so a StrictMode replay cannot
        // persist the same entry twice or interleave with the ref mirror.
        const nextMemory = {
          ...rowInstallNamesRef.current,
          [rowKey(item)]: res.name,
        };
        rowInstallNamesRef.current = nextMemory;
        setRowInstallNames(nextMemory);
        writeRowMemory(nextMemory);
        message.success(`${t("skills.importUrlSuccess")}: ${res.name}`);
        if (res.renamed_from) {
          message.warning(
            t("skills.importUrlRenamed", {
              from: res.renamed_from,
              to: res.name,
            }),
          );
        }
        onInstalled();
      } catch (error) {
        message.error(
          error instanceof Error ? error.message : t("skills.importUrlFailed"),
        );
      } finally {
        const next = new Set(installingRef.current);
        next.delete(item.slug);
        installingRef.current = next;
        setInstalling((prev) => {
          const s = new Set(prev);
          s.delete(item.slug);
          return s;
        });
      }
    },
    [installed, isRowInstalled, onInstalled, t],
  );

  // Run initial search when modal opens.
  useEffect(() => {
    if (open) {
      setQuery("");
      setCommittedQuery("");
      setResults([]);
      resultsRef.current = [];
      setSearched(false);
      setHasMore(false);
      setPage(1);
      // The pane's list is refetched on every install, so this session's
      // bridge would keep reporting "installed" for a skill deleted
      // meanwhile. The row-to-name memory stays: it is validated against the
      // library on every render, so only skills that still exist match.
      setLocalInstalled(new Set());
      void doSearch("", 1);
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Modal
      open={open}
      title={
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <ShoppingBag size={18} />
          {t("skills.marketTitle")}
        </span>
      }
      onCancel={onClose}
      footer={null}
      width={780}
      centered
      styles={{
        body: { maxHeight: "70vh", overflow: "auto", padding: "16px 24px" },
      }}
    >
      <div
        style={{
          fontSize: 12,
          color: "var(--color-text-tertiary)",
          marginBottom: 14,
          lineHeight: 1.5,
        }}
      >
        {t("skills.marketDesc")}
      </div>

      {/* Markets the runtime cannot reach, named with the host's own reason. */}
      {unavailableProviders.length > 0 && (
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 6,
            flexWrap: "wrap",
            fontSize: 11.5,
            lineHeight: 1.5,
            color: "var(--color-warning)",
            marginBottom: 12,
          }}
        >
          <Globe size={13} style={{ marginTop: 2 }} />
          <span>
            {t("skills.marketProviderUnavailable", {
              providers: unavailableProviders
                .map((provider) =>
                  provider.reason
                    ? `${provider.label} (${provider.reason})`
                    : provider.label,
                )
                .join(", "),
            })}
          </span>
        </div>
      )}

      {/* Search bar */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <Input
          ref={inputRef}
          value={query}
          placeholder={t("skills.marketSearchPlaceholder")}
          prefix={
            <Search size={14} style={{ color: "var(--color-text-tertiary)" }} />
          }
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={handleSearch}
          style={{ flex: 1 }}
          allowClear
        />
        <Button
          type="primary"
          icon={<Search size={14} />}
          onClick={handleSearch}
          loading={loading}
        >
          {t("common.search")}
        </Button>
      </div>

      {/* Loading state */}
      {loading && results.length === 0 && (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            padding: "60px 0",
          }}
        >
          <Spin size="large" />
        </div>
      )}

      {/* Empty state */}
      {!loading && searched && results.length === 0 && (
        <div
          style={{
            textAlign: "center",
            padding: "60px 0",
            color: "var(--color-text-tertiary)",
            fontSize: 13,
          }}
        >
          <AppWindow size={36} style={{ marginBottom: 12, opacity: 0.4 }} />
          <div>{t("skills.marketNoResults")}</div>
        </div>
      )}

      {/* Results grid */}
      {results.length > 0 && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
              gap: 10,
            }}
          >
            {results.map((item) => {
              const isInstalled = isRowInstalled(item);
              const isInstalling = installing.has(item.slug);
              const disabled = isInstalled || isInstalling;
              return (
                <div
                  key={rowKey(item)}
                  style={{
                    border: "1px solid var(--color-border)",
                    borderRadius: 10,
                    padding: "12px 14px",
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                    background: isInstalled
                      ? "var(--color-bg-layout)"
                      : undefined,
                  }}
                >
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    {item.icon_url ? (
                      <img
                        src={item.icon_url}
                        alt=""
                        style={{ width: 20, height: 20, borderRadius: 4 }}
                      />
                    ) : (
                      <Globe
                        size={14}
                        style={{ color: "var(--color-text-tertiary)" }}
                      />
                    )}
                    <span
                      style={{
                        flex: 1,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {item.name}
                    </span>
                    <Button
                      size="small"
                      type={isInstalled ? "default" : "primary"}
                      disabled={disabled}
                      loading={isInstalling}
                      icon={isInstalled ? undefined : <Download size={13} />}
                      onClick={() => handleInstall(item)}
                      style={{ flexShrink: 0 }}
                    >
                      {isInstalled
                        ? t("skills.marketInstalled")
                        : isInstalling
                        ? t("skills.marketInstalling")
                        : t("skills.marketInstall")}
                    </Button>
                  </div>

                  {item.description && (
                    <div
                      style={{
                        fontSize: 11.5,
                        color: "var(--color-text-secondary)",
                        lineHeight: 1.5,
                        overflow: "hidden",
                        display: "-webkit-box",
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: "vertical" as const,
                      }}
                    >
                      {item.description}
                    </div>
                  )}

                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--color-text-tertiary)",
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      flexWrap: "wrap",
                    }}
                  >
                    <span
                      style={{ display: "flex", alignItems: "center", gap: 4 }}
                      title={t("skills.marketSource")}
                    >
                      <ShoppingBag size={11} />
                      {sourceLabel(item.source, item.source_label)}
                    </span>
                    {item.author && (
                      <span
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                        title={t("skills.marketAuthor")}
                      >
                        <User size={11} />
                        {item.author}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Load more */}
          {hasMore && (
            <div style={{ textAlign: "center", marginTop: 16 }}>
              <Button onClick={handleLoadMore} loading={loading}>
                {t("common.more")}
              </Button>
            </div>
          )}

          {/* Loading indicator for subsequent pages */}
          {loading && results.length > 0 && (
            <div style={{ textAlign: "center", marginTop: 12 }}>
              <Spin size="small" />
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

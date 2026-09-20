import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Badge,
  Button,
  Empty,
  Input,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import {
  CheckCircle,
  Package,
  RefreshCw,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";
import { useIsMobile } from "@/hooks/useIsMobile";
import type { PluginInfo, PluginUpdateInfo } from "@/api/modules/plugin";
import { usePluginColumns } from "../hooks/usePluginColumns";
import { PluginTypeTag } from "./PluginTypeTag";
import { PluginViewToggle, type PluginViewMode } from "./PluginViewToggle";
import cardStyles from "./MarketPluginList.module.less";
import rowStyles from "./OfficialPluginList.module.less";
import toolbarStyles from "./PluginListToolbar.module.less";
import pageStyles from "../index.module.less";

const { Text } = Typography;

interface InstalledPluginListProps {
  plugins?: PluginInfo[];
  loading: boolean;
  uninstallingId: string | null;
  onRefresh: () => void;
  onUninstall: (plugin: PluginInfo) => void;
  updates: ReadonlyMap<string, PluginUpdateInfo>;
  updatesLoading: boolean;
  updatingId: string | null;
  updatingAll: boolean;
  onUpdate: (plugin: PluginInfo) => void;
  onUpdateAll: () => void;
}

export function InstalledPluginList({
  plugins = [],
  loading,
  uninstallingId,
  onRefresh,
  onUninstall,
  updates,
  updatesLoading,
  updatingId,
  updatingAll,
  onUpdate,
  onUpdateAll,
}: InstalledPluginListProps) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [viewMode, setViewMode] = useState<PluginViewMode>("card");
  const isMobile = useIsMobile();

  const columns = usePluginColumns({ uninstallingId, onUninstall });

  const filteredPlugins = useMemo(() => {
    const keyword = search.trim().toLocaleLowerCase();
    return plugins.filter(
      (plugin) => !keyword || plugin.name.toLocaleLowerCase().includes(keyword),
    );
  }, [plugins, search]);

  const renderStatus = (plugin: PluginInfo) =>
    plugin.loaded ? (
      <Tag
        icon={<CheckCircle size={12} />}
        color="success"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          margin: 0,
        }}
      >
        {t("pluginManager.statusLoaded")}
      </Tag>
    ) : (
      <Tag
        icon={<XCircle size={12} />}
        color="default"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          margin: 0,
        }}
      >
        {t("pluginManager.statusUnloaded")}
      </Tag>
    );

  const renderUpdateAction = (plugin: PluginInfo) => {
    const update = updates.get(plugin.id);
    if (!update) return null;
    return (
      <Button
        type="primary"
        icon={<Upload size={14} />}
        loading={updatingId === plugin.id}
        disabled={
          updatingAll || (updatingId !== null && updatingId !== plugin.id)
        }
        onClick={() => onUpdate(plugin)}
      >
        {t("pluginManager.update")}
      </Button>
    );
  };

  return (
    <div>
      <div className={toolbarStyles.controlRow}>
        <Input
          className={toolbarStyles.search}
          placeholder={t("pluginManager.filterByName")}
          allowClear
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className={toolbarStyles.controlActions}>
          {updates.size > 0 && (
            <Button
              type="primary"
              icon={<Upload size={14} />}
              loading={updatingAll}
              disabled={updatesLoading || updatingId !== null}
              onClick={onUpdateAll}
            >
              {t("pluginManager.updateAll")}
              <Badge count={updates.size} style={{ marginLeft: 6 }} />
            </Button>
          )}
          <Button
            type="default"
            className={toolbarStyles.iconButton}
            icon={<RefreshCw size={14} />}
            onClick={onRefresh}
            disabled={loading}
            aria-label={t("pluginManager.catalogRefresh")}
            title={t("pluginManager.catalogRefresh")}
          />
          {!isMobile && (
            <PluginViewToggle value={viewMode} onChange={setViewMode} />
          )}
        </div>
      </div>

      {updatesLoading && (
        <Alert
          type="info"
          showIcon
          message={t("pluginManager.checkingUpdates")}
          style={{ marginBottom: 12 }}
        />
      )}

      <Spin spinning={loading}>
        {!loading && filteredPlugins.length === 0 ? (
          <Empty
            image={<Package size={48} strokeWidth={1} />}
            description={
              plugins.length === 0
                ? t("pluginManager.noPlugins")
                : t("pluginManager.noMatchingPlugins")
            }
            style={{ marginTop: 24 }}
          />
        ) : isMobile || viewMode === "card" ? (
          <div className={cardStyles.cardGrid}>
            {filteredPlugins.map((plugin) => (
              <article
                className={cardStyles.pluginCard}
                key={plugin.id}
                aria-label={plugin.name}
              >
                <div className={cardStyles.cardTopRow}>
                  <div className={cardStyles.cardIcon}>
                    <Package size={18} />
                  </div>
                  {renderStatus(plugin)}
                </div>
                <div className={cardStyles.cardTitleRow}>
                  <Text
                    strong
                    ellipsis={{ tooltip: plugin.name }}
                    className={cardStyles.cardTitle}
                  >
                    {plugin.name}
                  </Text>
                  <PluginTypeTag type={plugin.plugin_type ?? "general"} />
                </div>
                <div className={cardStyles.cardDescription}>
                  {plugin.description || t("market.noDescription")}
                </div>
                <div className={cardStyles.cardFooter}>
                  <span className={cardStyles.cardMetadata}>
                    v{plugin.version}
                    {plugin.author ? ` · ${plugin.author}` : ""}
                  </span>
                </div>
                <div className={cardStyles.cardActions}>
                  {renderUpdateAction(plugin)}
                  <Button
                    danger
                    icon={<Trash2 size={14} />}
                    loading={uninstallingId === plugin.id}
                    disabled={
                      uninstallingId !== null && uninstallingId !== plugin.id
                    }
                    onClick={() => onUninstall(plugin)}
                  >
                    {t("pluginManager.uninstall")}
                  </Button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <>
            <div className={pageStyles.desktopTableList}>
              <Table
                dataSource={filteredPlugins}
                columns={columns}
                rowKey="id"
                pagination={false}
                className={pageStyles.table}
              />
            </div>
            <div
              className={`${rowStyles.catalogList} ${pageStyles.mobileTableList}`}
            >
              {filteredPlugins.map((plugin) => (
                <div className={rowStyles.catalogRow} key={plugin.id}>
                  <div className={rowStyles.catalogIcon}>
                    <Package size={18} />
                  </div>
                  <div className={rowStyles.catalogInfo}>
                    <div className={rowStyles.catalogNameRow}>
                      <Text strong>{plugin.name}</Text>
                      <PluginTypeTag type={plugin.plugin_type ?? "general"} />
                      {renderStatus(plugin)}
                    </div>
                    {plugin.description && (
                      <div className={rowStyles.catalogDescription}>
                        {plugin.description}
                      </div>
                    )}
                    <div className={rowStyles.catalogMeta}>
                      v{plugin.version}
                      {plugin.author ? ` · ${plugin.author}` : ""}
                    </div>
                  </div>
                  <div className={rowStyles.catalogActions}>
                    {renderUpdateAction(plugin)}
                    <Button
                      danger
                      icon={<Trash2 size={14} />}
                      loading={uninstallingId === plugin.id}
                      disabled={
                        uninstallingId !== null && uninstallingId !== plugin.id
                      }
                      onClick={() => onUninstall(plugin)}
                    >
                      {t("pluginManager.uninstall")}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </Spin>
    </div>
  );
}

import React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { ExternalLink, Package, Plus } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { usePluginManager } from "./hooks/usePluginManager";
import { usePluginColumns } from "./hooks/usePluginColumns";
import { useInstallModal } from "./hooks/useInstallModal";
import { InstallPluginModal } from "./components/InstallPluginModal";
import { OfficialPluginList } from "./components/OfficialPluginList";
import { MarketPluginList } from "./components/MarketPluginList";
import styles from "./index.module.less";

export default function PluginManagerPage() {
  const { t } = useTranslation();

  const {
    plugins,
    loading,
    refresh,
    uninstallingId,
    handleUninstall,
    confirmPlugin,
    setConfirmPlugin,
    confirmUninstall,
  } = usePluginManager();

  const installModal = useInstallModal(refresh);

  const columns = usePluginColumns({
    uninstallingId,
    onUninstall: handleUninstall,
  });

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("nav.pluginManager")}
        extra={
          <>
            <Button
              variant="outline"
              onClick={() =>
                window.open("https://platform.agentscope.io/plugins", "_blank")
              }
            >
              <ExternalLink size={16} className="mr-2" />
              {t("pluginManager.publishBtn")}
            </Button>
            <Button onClick={installModal.openModal}>
              <Plus size={16} className="mr-2" />
              {t("pluginManager.installBtn")}
            </Button>
          </>
        }
      />

      <div className={styles.content}>
        <Tabs defaultValue="installed" className={styles.tabs}>
          <TabsList>
            <TabsTrigger value="installed">
              {t("pluginManager.installed")}
            </TabsTrigger>
            <TabsTrigger value="official">
              {t("pluginManager.officialTitle")}
            </TabsTrigger>
            <TabsTrigger value="market">
              {t("pluginManager.marketTitle")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="installed">
            <div className={loading ? "opacity-60 pointer-events-none" : ""}>
              {!loading && (!plugins || plugins.length === 0) ? (
                <div className="flex flex-col items-center justify-center py-12 gap-2 text-muted-foreground">
                  <Package size={48} strokeWidth={1} />
                  <span>{t("pluginManager.noPlugins")}</span>
                </div>
              ) : (
                <Table className={styles.table}>
                  <TableHeader>
                    <TableRow>
                      {columns.map((col) => (
                        <TableHead
                          key={col.key}
                          style={col.width ? { width: col.width } : {}}
                        >
                          {col.title}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(plugins ?? []).map((plugin) => (
                      <TableRow key={plugin.id}>
                        {columns.map((col) => (
                          <TableCell key={col.key}>
                            {col.render
                              ? (
                                  col.render as (
                                    v: unknown,
                                    r: typeof plugin,
                                  ) => React.ReactNode
                                )(
                                  col.dataIndex
                                    ? (plugin as any)[col.dataIndex as string]
                                    : undefined,
                                  plugin,
                                )
                              : col.dataIndex
                              ? (plugin as any)[col.dataIndex as string]
                              : null}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>
          </TabsContent>

          <TabsContent value="official">
            <OfficialPluginList onInstalled={refresh} />
          </TabsContent>

          <TabsContent value="market">
            <MarketPluginList onInstalled={refresh} />
          </TabsContent>
        </Tabs>
      </div>

      <InstallPluginModal {...installModal} />

      <AlertDialog
        open={!!confirmPlugin}
        onOpenChange={(v) => {
          if (!v) setConfirmPlugin(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("pluginManager.confirmTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("pluginManager.uninstallConfirm", {
                name: confirmPlugin?.name ?? "",
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={confirmUninstall}
            >
              {t("pluginManager.uninstall")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

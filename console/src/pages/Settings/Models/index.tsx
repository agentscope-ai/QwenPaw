import { useMemo, useState } from "react";
import { Button } from "@agentscope-ai/design";
import { PlusOutlined } from "@ant-design/icons";
import { useProviders } from "./useProviders";
import {
  PageHeader,
  LoadingState,
  ProviderCard,
  ModelsSection,
  CustomProviderModal,
} from "./components";
import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "../../../api/types/provider";
import styles from "./index.module.less";

/* ------------------------------------------------------------------ */
/* Main Page                                                           */
/* ------------------------------------------------------------------ */

function ModelsPage() {
  const { t } = useTranslation();
  const { providers, activeModels, loading, error, fetchAll } = useProviders();
  const [hoveredCard, setHoveredCard] = useState<string | null>(null);
  const [addProviderOpen, setAddProviderOpen] = useState(false);

  const refreshProvidersSilently = () => fetchAll(false);

  const { regularProviders, embeddedProviders } = useMemo(() => {
    const regular: ProviderInfo[] = [];
    const embedded: ProviderInfo[] = [];
    for (const p of providers) {
      if (p.is_local) embedded.push(p);
      else regular.push(p);
    }
    return { regularProviders: regular, embeddedProviders: embedded };
  }, [providers]);

  const handleMouseEnter = (providerId: string) => {
    setHoveredCard(providerId);
  };

  const handleMouseLeave = () => {
    setHoveredCard(null);
  };

  const renderProviderCards = (list: ProviderInfo[]) =>
    list.map((provider) => (
      <ProviderCard
        key={provider.id}
        provider={provider}
        activeModels={activeModels}
        onSaved={refreshProvidersSilently}
        isHover={hoveredCard === provider.id}
        onMouseEnter={() => handleMouseEnter(provider.id)}
        onMouseLeave={handleMouseLeave}
      />
    ));

  return (
    <div className={styles.settingsPage}>
      {loading ? (
        <LoadingState message={t("models.loading")} />
      ) : error ? (
        <LoadingState message={error} error onRetry={fetchAll} />
      ) : (
        <>
          {/* ---- LLM Section (top) ---- */}
          <PageHeader
            title={t("models.llmTitle")}
            description={t("models.llmDescription")}
          />
          <ModelsSection
            providers={providers}
            activeModels={activeModels}
            onSaved={fetchAll}
          />

          {/* ---- Providers Section (below) ---- */}
          <div className={styles.providersBlock}>
            <div className={styles.sectionHeaderRow}>
              <PageHeader
                title={t("models.providersTitle")}
                description={t("models.providersDescription")}
              />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setAddProviderOpen(true)}
                className={styles.addProviderBtn}
              >
                {t("models.addProvider")}
              </Button>
            </div>

            {regularProviders.length > 0 && (
              <div className={styles.providerGroup}>
                <div className={styles.providerCards}>
                  {renderProviderCards(regularProviders)}
                </div>
              </div>
            )}

            {embeddedProviders.length > 0 && (
              <div className={styles.providerGroup}>
                <h4 className={styles.providerGroupTitle}>
                  {t("models.localEmbedded")}
                </h4>
                <div className={styles.providerCards}>
                  {renderProviderCards(embeddedProviders)}
                </div>
              </div>
            )}
          </div>

          <CustomProviderModal
            open={addProviderOpen}
            onClose={() => setAddProviderOpen(false)}
            onSaved={fetchAll}
          />
        </>
      )}
    </div>
  );
}

export default ModelsPage;

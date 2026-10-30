import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { openExternalLink } from "@/utils/openExternalLink";
import { communityRelatedApi } from "./api";
import styles from "./index.module.less";

interface CardData {
  key: string;
  url: string;
  title: string;
  versionLabel?: string;
  description?: string;
  iconUrl?: string;
  initials: string;
  kind: "skill" | "plugin";
}

function toInitials(title: string): string {
  const cleaned = title.replace(/[^a-zA-Z0-9一-鿿]/g, "");
  if (!cleaned) return "QW";
  if (/[一-鿿]/.test(cleaned)) return cleaned.slice(0, 2);
  const parts = title.split(/[-_\s]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return cleaned.slice(0, 2).toUpperCase();
}

function textOf(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

/** Related skill/plugin cards shown above the article body. */
export function RelatedResources({
  skillIds = [],
  pluginIds = [],
}: {
  skillIds?: string[];
  pluginIds?: string[];
}) {
  const { t } = useTranslation();
  const [cards, setCards] = useState<CardData[]>([]);
  const skillKey = skillIds.slice(0, 3).join(",");
  const pluginKey = pluginIds.slice(0, 3).join(",");

  useEffect(() => {
    let cancelled = false;
    const skills = skillKey ? skillKey.split(",") : [];
    const plugins = pluginKey ? pluginKey.split(",") : [];
    if (!skills.length && !plugins.length) {
      setCards([]);
      return;
    }
    const next: CardData[] = [];
    Promise.all([
      ...skills.map(async (skillId) => {
        try {
          const data = await communityRelatedApi.skill(skillId);
          const title = textOf(data.skill_code) || textOf(data.name) || skillId;
          next.push({
            key: `skill-${skillId}`,
            url: `https://platform.agentscope.io/skills/${encodeURIComponent(
              skillId,
            )}`,
            title,
            versionLabel: textOf(data.version_label)
              ? `V${data.version_label}`
              : undefined,
            description: textOf(data.description),
            iconUrl: textOf(data.icon_url),
            initials: toInitials(title),
            kind: "skill",
          });
        } catch {
          // Missing related resources simply hide their card.
        }
      }),
      ...plugins.map(async (pluginId) => {
        try {
          const data = await communityRelatedApi.plugin(pluginId);
          const title = textOf(data.name) || pluginId;
          next.push({
            key: `plugin-${pluginId}`,
            url: `https://platform.agentscope.io/plugins/${encodeURIComponent(
              pluginId,
            )}`,
            title,
            versionLabel: textOf(data.version_label)
              ? `V${data.version_label}`
              : undefined,
            description: textOf(data.description),
            iconUrl: textOf(data.icon_url),
            initials: toInitials(title),
            kind: "plugin",
          });
        } catch {
          // Missing related resources simply hide their card.
        }
      }),
    ]).then(() => {
      if (!cancelled) setCards(next);
    });
    return () => {
      cancelled = true;
    };
  }, [skillKey, pluginKey]);

  if (!cards.length) return null;
  const skillCards = cards.filter((card) => card.kind === "skill");
  const pluginCards = cards.filter((card) => card.kind === "plugin");

  const renderSection = (titleKey: string, list: CardData[], hintKey: string) =>
    list.length > 0 && (
      <section>
        <h3 className={styles.relatedTitle}>{t(titleKey)}</h3>
        <div
          className={`${styles.relatedGrid} ${
            list.length > 1 ? styles.relatedGridWide : ""
          }`}
        >
          {list.map((card, index) => (
            <div
              key={card.key}
              className={
                list.length === 3 && index === 2 ? styles.relatedSpan : ""
              }
            >
              <a
                className={styles.relatedCard}
                href={card.url}
                onClick={(event) => {
                  event.preventDefault();
                  openExternalLink(card.url);
                }}
              >
                {card.iconUrl ? (
                  <img
                    src={card.iconUrl}
                    alt=""
                    className={`${styles.relatedIcon} ${
                      card.kind === "plugin"
                        ? styles.relatedIconPlugin
                        : styles.relatedIconSkill
                    }`}
                  />
                ) : (
                  <span
                    className={`${styles.relatedIcon} ${
                      card.kind === "plugin"
                        ? styles.relatedIconPlugin
                        : styles.relatedIconSkill
                    }`}
                  >
                    {card.initials}
                  </span>
                )}
                <span className={styles.relatedMain}>
                  <span className={styles.relatedNameRow}>
                    <span className={styles.relatedName}>{card.title}</span>
                    {card.versionLabel && (
                      <span className={styles.relatedVersion}>
                        {card.versionLabel}
                      </span>
                    )}
                  </span>
                  <span className={styles.relatedDesc}>
                    {card.description || t(hintKey)}
                  </span>
                </span>
              </a>
            </div>
          ))}
        </div>
      </section>
    );

  return (
    <div className={styles.relatedBox}>
      {renderSection(
        "communityPage.relatedSkillsTitle",
        skillCards,
        "communityPage.relatedSkillHint",
      )}
      {renderSection(
        "communityPage.relatedPluginsTitle",
        pluginCards,
        "communityPage.relatedPluginHint",
      )}
    </div>
  );
}

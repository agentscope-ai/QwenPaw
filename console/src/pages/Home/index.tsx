import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  MessageOutlined,
  ThunderboltOutlined,
  ApiOutlined,
  SettingOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import styles from "./index.module.less";

interface SuggestionCard {
  key: string;
  icon: React.ReactNode;
  titleKey: string;
  descKey: string;
  route: string;
}

const SUGGESTION_CARDS: SuggestionCard[] = [
  {
    key: "chat",
    icon: <MessageOutlined />,
    titleKey: "home.cards.chat.title",
    descKey: "home.cards.chat.desc",
    route: "/chat",
  },
  {
    key: "skills",
    icon: <ThunderboltOutlined />,
    titleKey: "home.cards.skills.title",
    descKey: "home.cards.skills.desc",
    route: "/skills",
  },
  {
    key: "mcp",
    icon: <ApiOutlined />,
    titleKey: "home.cards.mcp.title",
    descKey: "home.cards.mcp.desc",
    route: "/mcp",
  },
  {
    key: "settings",
    icon: <SettingOutlined />,
    titleKey: "home.cards.settings.title",
    descKey: "home.cards.settings.desc",
    route: "/agents",
  },
];

export default function HomePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className={styles.page}>
      <div className={styles.hero}>
        <div className={styles.avatar}>
          <span className={styles.avatarIcon}>
            <RobotOutlined />
          </span>
        </div>
        <h1 className={styles.title}>{t("home.title")}</h1>
        <p className={styles.subtitle}>{t("home.subtitle")}</p>
      </div>

      <div className={styles.cards}>
        {SUGGESTION_CARDS.map((card) => (
          <button
            key={card.key}
            className={styles.card}
            onClick={() => navigate(card.route)}
            type="button"
          >
            <span className={styles.cardIcon}>{card.icon}</span>
            <span className={styles.cardContent}>
              <span className={styles.cardTitle}>{t(card.titleKey)}</span>
              <span className={styles.cardDesc}>{t(card.descKey)}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

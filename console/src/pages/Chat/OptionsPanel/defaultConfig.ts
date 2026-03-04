import i18n from "../../../i18n";

const getDefaultConfig = () => ({
  theme: {
    colorPrimary: "#615CED",
    darkMode: false,
    prefix: "copaw",
    leftHeader: {
      logo: "",
      title: i18n.t("chat.leftHeaderTitle"),
    },
  },
  sender: {
    attachments: false,
    maxLength: 10000,
    disclaimer: i18n.t("chat.disclaimer"),
  },
  welcome: {
    greeting: i18n.t("chat.welcomeGreeting"),
    description: i18n.t("chat.welcomeDescription"),
    avatar: `${import.meta.env.BASE_URL}copaw-symbol.svg`,
    prompts: [
      {
        value: i18n.t("chat.defaultPrompt1"),
      },
      {
        value: i18n.t("chat.defaultPrompt2"),
      },
    ],
  },
  api: {
    baseURL: "",
    token: "",
  },
});

export default getDefaultConfig;

export type DefaultConfig = ReturnType<typeof getDefaultConfig>;

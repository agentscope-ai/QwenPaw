export const providerIcon = (provider: string) => {
  switch (provider) {
    case "modelscope":
      return "/icons/providers/modelscope.png";
    case "aliyun-codingplan":
      return "/icons/providers/aliyun-codingplan.png";
    case "deepseek":
      return "/icons/providers/deepseek.png";
    case "gemini":
      return "/icons/providers/gemini.png";
    case "azure-openai":
      return "/icons/providers/azure-openai.png";
    case "kimi-cn":
    case "kimi-intl":
      return "/icons/providers/kimi.png";
    case "anthropic":
      return "/icons/providers/anthropic.png";
    case "ollama":
      return "/icons/providers/ollama.png";
    case "minimax-cn":
    case "minimax":
      return "/icons/providers/minimax.png";
    case "openai":
      return "/icons/providers/openai.png";
    case "dashscope":
      return "/icons/providers/dashscope.png";
    case "lmstudio":
      return "/icons/providers/lmstudio.png";
    case "siliconflow-cn":
      return "/icons/providers/siliconflow.png";
    case "siliconflow-intl":
      return "/icons/providers/siliconflow.png";
    case "qwenpaw-local":
      return "/icons/providers/qwenpaw-local.png";
    case "zhipu-cn":
    case "zhipu-intl":
    case "zhipu-cn-codingplan":
    case "zhipu-intl-codingplan":
      return "/icons/providers/zhipu.png";
    case "openrouter":
      return "/icons/providers/openrouter.png";
    case "opencode":
      return "/icons/providers/opencode.png";
    default:
      return "/icons/providers/default.jpg";
  }
};

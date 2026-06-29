import type {
  AgentsLLMFallbackConfig,
  AgentsLLMRoutingConfig,
} from "../../../api/types";

export function mergeFallbackRoutingConfig(
  config: AgentsLLMRoutingConfig,
  fallback: AgentsLLMFallbackConfig,
): AgentsLLMRoutingConfig {
  return {
    ...config,
    fallback,
  };
}

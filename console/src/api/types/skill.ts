export interface SkillSpec {
  name: string;
  description?: string;
  content: string;
  source: string;
  path: string;
  enabled?: boolean;
}

export interface HubSkillSpec {
  slug: string;
  name: string;
  description: string;
  version: string;
  source_url: string;
}

export interface SkillsMarketSpec {
  id: string;
  name: string;
  url: string;
  branch?: string;
  path: string;
  enabled: boolean;
  order: number;
  trust?: "official" | "community" | "custom" | null;
}

export interface SkillsMarketsPayload {
  version: number;
  cache: {
    ttl_sec: number;
  };
  install: {
    overwrite_default: boolean;
  };
  markets: SkillsMarketSpec[];
}

export interface ValidateMarketResponse {
  ok: boolean;
  normalized: SkillsMarketSpec;
  warnings: string[];
}

export interface MarketError {
  market_id: string;
  code: string;
  message: string;
  retryable: boolean;
}

export interface MarketplaceItem {
  market_id: string;
  skill_id: string;
  name: string;
  description: string;
  version: string;
  source_url: string;
  install_url: string;
  tags: string[];
}

export interface MarketplaceMeta {
  enabled_market_count: number;
  success_market_count: number;
  item_count: number;
}

export interface MarketplaceResponse {
  items: MarketplaceItem[];
  market_errors: MarketError[];
  meta: MarketplaceMeta;
}

export interface InstallMarketplacePayload {
  market_id: string;
  skill_id: string;
  enable?: boolean;
  overwrite?: boolean;
}

export interface InstallSkillResult {
  installed: boolean;
  name: string;
  enabled: boolean;
  source_url: string;
}

// Legacy Skill interface for backward compatibility
export interface Skill {
  id: string;
  name: string;
  description: string;
  function_name: string;
  enabled: boolean;
  version: string;
  tags: string[];
  created_at: number;
  updated_at: number;
}

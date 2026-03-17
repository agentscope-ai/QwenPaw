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

import type { MCPMarketIconId } from "./templateIcons";

export type MCPFieldType = "secret" | "text" | "path";

export type MCPCategory =
  | "official"
  | "dev"
  | "data"
  | "web"
  | "productivity"
  | "cloud";

export interface MCPMarketField {
  key: string;
  labelKey: string;
  type: MCPFieldType;
  required?: boolean;
  placeholderKey?: string;
  envKey?: string;
  /** For streamable_http: map field to Authorization (or other) header */
  headerKey?: string;
  headerPrefix?: string;
}

export interface MCPMarketTemplate {
  id: string;
  nameKey: string;
  descriptionKey: string;
  category: MCPCategory;
  iconId: MCPMarketIconId;
  transport: "stdio" | "streamable_http" | "sse";
  command?: string;
  args?: string[];
  url?: string;
  envDefaults?: Record<string, string>;
  fields: MCPMarketField[];
  docsUrl?: string;
}

/** Stable documentation links (npm / official repo / product docs). */
const NPM = (pkg: string) => `https://www.npmjs.com/package/${pkg}`;

export const MCP_CATEGORIES: MCPCategory[] = [
  "official",
  "dev",
  "data",
  "web",
  "productivity",
  "cloud",
];

const templateById = new Map<string, MCPMarketTemplate>();

export const mcpTemplates: MCPMarketTemplate[] = [
  {
    id: "filesystem",
    nameKey: "mcp.market.templates.filesystem.name",
    descriptionKey: "mcp.market.templates.filesystem.description",
    category: "official",
    iconId: "filesystem",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-filesystem"],
    fields: [
      {
        key: "allowed_directories",
        labelKey: "mcp.market.templates.filesystem.fields.allowed_directories",
        type: "path",
        required: true,
        placeholderKey:
          "mcp.market.templates.filesystem.fields.allowed_directoriesPlaceholder",
      },
    ],
    docsUrl: NPM("@modelcontextprotocol/server-filesystem"),
  },
  {
    id: "fetch",
    nameKey: "mcp.market.templates.fetch.name",
    descriptionKey: "mcp.market.templates.fetch.description",
    category: "web",
    iconId: "fetch",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-fetch"],
    fields: [],
    docsUrl: NPM("@modelcontextprotocol/server-fetch"),
  },
  {
    id: "github",
    nameKey: "mcp.market.templates.github.name",
    descriptionKey: "mcp.market.templates.github.description",
    category: "dev",
    iconId: "github",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-github"],
    fields: [
      {
        key: "GITHUB_PERSONAL_ACCESS_TOKEN",
        labelKey: "mcp.market.templates.github.fields.token",
        type: "secret",
        required: true,
      },
    ],
    docsUrl: "https://github.com/github/github-mcp-server",
  },
  {
    id: "gitee",
    nameKey: "mcp.market.templates.gitee.name",
    descriptionKey: "mcp.market.templates.gitee.description",
    category: "dev",
    iconId: "gitee",
    transport: "streamable_http",
    url: "https://api.gitee.com/mcp",
    fields: [
      {
        key: "GITEE_ACCESS_TOKEN",
        labelKey: "mcp.market.templates.gitee.fields.token",
        type: "secret",
        required: true,
        headerKey: "Authorization",
        headerPrefix: "Bearer ",
        placeholderKey: "mcp.market.templates.gitee.fields.tokenPlaceholder",
      },
    ],
    docsUrl: "https://help.gitee.com/ai-productivity/mcp-server",
  },
  {
    id: "gitlab",
    nameKey: "mcp.market.templates.gitlab.name",
    descriptionKey: "mcp.market.templates.gitlab.description",
    category: "dev",
    iconId: "gitlab",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-gitlab"],
    fields: [
      {
        key: "GITLAB_PERSONAL_ACCESS_TOKEN",
        labelKey: "mcp.market.templates.gitlab.fields.token",
        type: "secret",
        required: true,
      },
    ],
    docsUrl: NPM("@modelcontextprotocol/server-gitlab"),
  },
  {
    id: "postgres",
    nameKey: "mcp.market.templates.postgres.name",
    descriptionKey: "mcp.market.templates.postgres.description",
    category: "data",
    iconId: "postgres",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-postgres"],
    fields: [
      {
        key: "POSTGRES_CONNECTION_STRING",
        labelKey: "mcp.market.templates.postgres.fields.connection",
        type: "secret",
        required: true,
        placeholderKey:
          "mcp.market.templates.postgres.fields.connectionPlaceholder",
      },
    ],
    docsUrl: NPM("@modelcontextprotocol/server-postgres"),
  },
  {
    id: "mysql",
    nameKey: "mcp.market.templates.mysql.name",
    descriptionKey: "mcp.market.templates.mysql.description",
    category: "data",
    iconId: "mysql",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@liangshanli/mcp-server-mysql"],
    envDefaults: { MYSQL_PORT: "3306" },
    fields: [
      {
        key: "MYSQL_HOST",
        labelKey: "mcp.market.templates.mysql.fields.host",
        type: "text",
        required: true,
        placeholderKey: "mcp.market.templates.mysql.fields.hostPlaceholder",
      },
      {
        key: "MYSQL_PORT",
        labelKey: "mcp.market.templates.mysql.fields.port",
        type: "text",
        required: false,
        placeholderKey: "mcp.market.templates.mysql.fields.portPlaceholder",
      },
      {
        key: "MYSQL_USER",
        labelKey: "mcp.market.templates.mysql.fields.user",
        type: "text",
        required: true,
      },
      {
        key: "MYSQL_PASSWORD",
        labelKey: "mcp.market.templates.mysql.fields.password",
        type: "secret",
        required: true,
      },
      {
        key: "MYSQL_DATABASE",
        labelKey: "mcp.market.templates.mysql.fields.database",
        type: "text",
        required: true,
        envKey: "MYSQL_DATABASE",
      },
      {
        key: "READONLY",
        labelKey: "mcp.market.templates.mysql.fields.readonly",
        type: "text",
        required: false,
        placeholderKey: "mcp.market.templates.mysql.fields.readonlyPlaceholder",
      },
    ],
    docsUrl: "https://www.npmjs.com/package/@liangshanli/mcp-server-mysql",
  },
  {
    id: "redis",
    nameKey: "mcp.market.templates.redis.name",
    descriptionKey: "mcp.market.templates.redis.description",
    category: "data",
    iconId: "redis",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-redis"],
    fields: [
      {
        key: "redis_url",
        labelKey: "mcp.market.templates.redis.fields.url",
        type: "text",
        required: true,
        placeholderKey: "mcp.market.templates.redis.fields.urlPlaceholder",
      },
    ],
    docsUrl: NPM("@modelcontextprotocol/server-redis"),
  },
  {
    id: "sqlite",
    nameKey: "mcp.market.templates.sqlite.name",
    descriptionKey: "mcp.market.templates.sqlite.description",
    category: "data",
    iconId: "sqlite",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-sqlite"],
    fields: [
      {
        key: "sqlite_path",
        labelKey: "mcp.market.templates.sqlite.fields.path",
        type: "path",
        required: true,
        placeholderKey: "mcp.market.templates.sqlite.fields.pathPlaceholder",
      },
    ],
    docsUrl:
      "https://github.com/modelcontextprotocol/servers-archived/tree/main/src/sqlite",
  },
  {
    id: "brave-search",
    nameKey: "mcp.market.templates.braveSearch.name",
    descriptionKey: "mcp.market.templates.braveSearch.description",
    category: "web",
    iconId: "brave-search",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-brave-search"],
    fields: [
      {
        key: "BRAVE_API_KEY",
        labelKey: "mcp.market.templates.braveSearch.fields.apiKey",
        type: "secret",
        required: true,
      },
    ],
    docsUrl: NPM("@modelcontextprotocol/server-brave-search"),
  },
  {
    id: "puppeteer",
    nameKey: "mcp.market.templates.puppeteer.name",
    descriptionKey: "mcp.market.templates.puppeteer.description",
    category: "web",
    iconId: "puppeteer",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-puppeteer"],
    fields: [],
    docsUrl: NPM("@modelcontextprotocol/server-puppeteer"),
  },
  {
    id: "slack",
    nameKey: "mcp.market.templates.slack.name",
    descriptionKey: "mcp.market.templates.slack.description",
    category: "productivity",
    iconId: "slack",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-slack"],
    fields: [
      {
        key: "SLACK_BOT_TOKEN",
        labelKey: "mcp.market.templates.slack.fields.botToken",
        type: "secret",
        required: true,
      },
      {
        key: "SLACK_TEAM_ID",
        labelKey: "mcp.market.templates.slack.fields.teamId",
        type: "text",
        required: true,
      },
    ],
    docsUrl: NPM("@modelcontextprotocol/server-slack"),
  },
  {
    id: "yuque",
    nameKey: "mcp.market.templates.yuque.name",
    descriptionKey: "mcp.market.templates.yuque.description",
    category: "productivity",
    iconId: "yuque",
    transport: "stdio",
    command: "npx",
    args: ["-y", "yuque-mcp"],
    fields: [
      {
        key: "YUQUE_PERSONAL_TOKEN",
        labelKey: "mcp.market.templates.yuque.fields.token",
        type: "secret",
        required: true,
        placeholderKey: "mcp.market.templates.yuque.fields.tokenPlaceholder",
      },
    ],
    docsUrl: "https://github.com/yuque/yuque-mcp-server",
  },
  {
    id: "memory",
    nameKey: "mcp.market.templates.memory.name",
    descriptionKey: "mcp.market.templates.memory.description",
    category: "data",
    iconId: "memory",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-memory"],
    fields: [],
    docsUrl: NPM("@modelcontextprotocol/server-memory"),
  },
  {
    id: "time",
    nameKey: "mcp.market.templates.time.name",
    descriptionKey: "mcp.market.templates.time.description",
    category: "official",
    iconId: "time",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-time"],
    fields: [],
    docsUrl: NPM("@modelcontextprotocol/server-time"),
  },
  {
    id: "aliyun-ack",
    nameKey: "mcp.market.templates.aliyunAck.name",
    descriptionKey: "mcp.market.templates.aliyunAck.description",
    category: "cloud",
    iconId: "aliyun",
    transport: "stdio",
    command: "uvx",
    args: ["alibabacloud-ack-mcp-server@latest"],
    fields: [
      {
        key: "ACCESS_KEY_ID",
        labelKey: "mcp.market.templates.aliyunCommon.fields.accessKeyId",
        type: "secret",
        required: true,
      },
      {
        key: "ACCESS_KEY_SECRET",
        labelKey: "mcp.market.templates.aliyunCommon.fields.accessKeySecret",
        type: "secret",
        required: true,
      },
    ],
    docsUrl: "https://github.com/aliyun/alibabacloud-ack-mcp-server",
  },
  {
    id: "aliyun-observability",
    nameKey: "mcp.market.templates.aliyunObservability.name",
    descriptionKey: "mcp.market.templates.aliyunObservability.description",
    category: "cloud",
    iconId: "aliyun",
    transport: "stdio",
    command: "uvx",
    args: ["mcp-server-aliyun-observability", "--transport", "stdio"],
    fields: [
      {
        key: "ALIBABA_CLOUD_ACCESS_KEY_ID",
        labelKey: "mcp.market.templates.aliyunCommon.fields.accessKeyId",
        type: "secret",
        required: true,
      },
      {
        key: "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
        labelKey: "mcp.market.templates.aliyunCommon.fields.accessKeySecret",
        type: "secret",
        required: true,
      },
      {
        key: "ALIBABA_CLOUD_REGION",
        labelKey: "mcp.market.templates.aliyunObservability.fields.region",
        type: "text",
        required: false,
        placeholderKey:
          "mcp.market.templates.aliyunObservability.fields.regionPlaceholder",
      },
    ],
    docsUrl: "https://github.com/aliyun/alibabacloud-observability-mcp-server",
  },
  {
    id: "aliyun-sls",
    nameKey: "mcp.market.templates.aliyunSls.name",
    descriptionKey: "mcp.market.templates.aliyunSls.description",
    category: "cloud",
    iconId: "aliyun",
    transport: "stdio",
    command: "npx",
    args: ["-y", "aliyun-sls-mcp"],
    fields: [
      {
        key: "ALIBABA_CLOUD_ACCESS_KEY_ID",
        labelKey: "mcp.market.templates.aliyunCommon.fields.accessKeyId",
        type: "secret",
        required: true,
      },
      {
        key: "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
        labelKey: "mcp.market.templates.aliyunCommon.fields.accessKeySecret",
        type: "secret",
        required: true,
      },
      {
        key: "SLS_REGION",
        labelKey: "mcp.market.templates.aliyunSls.fields.region",
        type: "text",
        required: false,
        placeholderKey:
          "mcp.market.templates.aliyunSls.fields.regionPlaceholder",
      },
    ],
    docsUrl: "https://www.npmjs.com/package/aliyun-sls-mcp",
  },
  {
    id: "jenkins",
    nameKey: "mcp.market.templates.jenkins.name",
    descriptionKey: "mcp.market.templates.jenkins.description",
    category: "dev",
    iconId: "jenkins",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@mister-good-deal/host-mcp-jenkins"],
    fields: [
      {
        key: "JENKINS_URL",
        labelKey: "mcp.market.templates.jenkins.fields.url",
        type: "text",
        required: true,
        placeholderKey: "mcp.market.templates.jenkins.fields.urlPlaceholder",
      },
      {
        key: "JENKINS_USER",
        labelKey: "mcp.market.templates.jenkins.fields.user",
        type: "text",
        required: true,
      },
      {
        key: "JENKINS_API_TOKEN",
        labelKey: "mcp.market.templates.jenkins.fields.apiToken",
        type: "secret",
        required: true,
        placeholderKey:
          "mcp.market.templates.jenkins.fields.apiTokenPlaceholder",
      },
    ],
    docsUrl: "https://www.npmjs.com/package/@mister-good-deal/host-mcp-jenkins",
  },
  {
    id: "remote-http",
    nameKey: "mcp.market.templates.remoteHttp.name",
    descriptionKey: "mcp.market.templates.remoteHttp.description",
    category: "dev",
    iconId: "remote-http",
    transport: "streamable_http",
    url: "https://mcp.example.com/mcp",
    fields: [
      {
        key: "url",
        labelKey: "mcp.market.templates.remoteHttp.fields.url",
        type: "text",
        required: true,
        placeholderKey: "mcp.market.templates.remoteHttp.fields.urlPlaceholder",
      },
    ],
    docsUrl: "https://modelcontextprotocol.io/docs/learn/server-concepts",
  },
];

for (const tpl of mcpTemplates) {
  templateById.set(tpl.id, tpl);
}

export function getMcpTemplateById(id: string): MCPMarketTemplate | undefined {
  return templateById.get(id);
}

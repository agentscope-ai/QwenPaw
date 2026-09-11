// Service hosts retained so backend-compatible config classification stays
// stable. They are not available as mailbox domains in the current console.
export const MAIL_ENTERPRISE_SERVICE_DOMAINS = [
  "exmail.qq.com",
  "qiye.aliyun.com",
  "qiye.163.com",
];

// Mail domains accepted by the backend without an explicit provider.
export const MAIL_DOMAIN_WHITELIST = [
  "163.com",
  "126.com",
  "yeah.net",
  "qq.com",
  "foxmail.com",
  "sina.com",
  "sina.cn",
  "aliyun.com",
  "gmail.com",
  ...MAIL_ENTERPRISE_SERVICE_DOMAINS,
];

const UNAVAILABLE_MAIL_DOMAINS = new Set(MAIL_ENTERPRISE_SERVICE_DOMAINS);

export const MAIL_DOMAIN_PICKER_DOMAINS = MAIL_DOMAIN_WHITELIST.filter(
  (domain) => !UNAVAILABLE_MAIL_DOMAINS.has(domain),
);

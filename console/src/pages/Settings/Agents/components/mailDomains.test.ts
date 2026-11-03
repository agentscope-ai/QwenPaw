import { describe, expect, it } from "vitest";

import {
  MAIL_DOMAIN_PICKER_DOMAINS,
  MAIL_DOMAIN_WHITELIST,
} from "./mailDomains";

const BACKEND_ONLY_ENTERPRISE_HOSTS = [
  "exmail.qq.com",
  "qiye.aliyun.com",
  "qiye.163.com",
];

describe("mail domain presets", () => {
  it("retains service hosts for compatibility without suggesting them", () => {
    expect(MAIL_DOMAIN_WHITELIST).toEqual(
      expect.arrayContaining(BACKEND_ONLY_ENTERPRISE_HOSTS),
    );
    expect(MAIL_DOMAIN_PICKER_DOMAINS).toEqual(
      MAIL_DOMAIN_WHITELIST.filter(
        (domain) => !BACKEND_ONLY_ENTERPRISE_HOSTS.includes(domain),
      ),
    );
  });
});

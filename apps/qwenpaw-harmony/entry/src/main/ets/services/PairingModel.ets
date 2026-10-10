/*
 * 配对码解析 —— 移植 PR #7378 src/api/pairing.ts 的 direct 分支（一期仅 LAN 直连）。
 * 配对码格式：qwenpaw://pair?v=1&base_url=<http(s) 地址>&ticket=<≥32 字符>
 * 远程中转配对（v2 JSON）一期不支持。
 */

import { url } from '@kit.ArkTS';

export interface DirectPairing {
  baseUrl: string;
  ticket: string;
}

// 地址规范化（对齐 PR #7378 api/pairing.ts normalizeBaseUrl 的标准 URL 解析，
// 并按业界 / NAS（飞牛等）惯例放宽输入）：
//   支持 IPv4 / IPv6（[::1]）/ 域名 / 显式或省略端口；未写协议时按 http:// 补全。
export function normalizeBaseUrl(value: string): string {
  let trimmed: string = value.trim();
  if (trimmed.length === 0) {
    throw new Error('请输入 QwenPaw 地址。');
  }
  // 业界惯例：裸 host[:port] 或 [IPv6][:port] 自动补 http://
  if (trimmed.indexOf('://') < 0) {
    trimmed = `http://${trimmed}`;
  }
  let parsed: url.URL;
  try {
    parsed = url.URL.parseURL(trimmed);
  } catch (e) {
    throw new Error('QwenPaw 地址格式无效。');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('QwenPaw 地址必须使用 HTTP 或 HTTPS。');
  }
  if (parsed.username.length > 0 || parsed.password.length > 0) {
    throw new Error('QwenPaw 地址不能带账号凭据。');
  }
  if (parsed.search.length > 0 || parsed.hash.length > 0) {
    throw new Error('QwenPaw 地址不能带查询参数。');
  }
  if (parsed.host.length === 0) {
    throw new Error('QwenPaw 地址缺少主机名。');
  }
  return parsed.toString().replace(/\/+$/, '');
}

// 展示用主机名（含端口；IPv6 保留方括号，如 [fe80::1]:8088）
export function hostOf(baseUrl: string): string {
  try {
    return url.URL.parseURL(baseUrl).host.toLowerCase();
  } catch (e) {
    return '';
  }
}

export function parsePairingUri(value: string): DirectPairing {
  const v: string = value.trim();
  if (v.startsWith('{')) {
    throw new Error('远程中转配对一期暂不支持（仅 LAN 直连）。');
  }
  if (!v.startsWith('qwenpaw://pair')) {
    throw new Error('这不是一个 QwenPaw 配对码。');
  }
  const params: Record<string, string> = {};
  const qIndex: number = v.indexOf('?');
  if (qIndex >= 0) {
    const pairs: string[] = v.slice(qIndex + 1).split('&');
    for (const p of pairs) {
      const eq: number = p.indexOf('=');
      if (eq <= 0) {
        continue;
      }
      params[decodeURIComponent(p.slice(0, eq))] = decodeURIComponent(p.slice(eq + 1));
    }
  }
  const version: number = Number(params['v'] !== undefined ? params['v'] : '0');
  const baseUrl: string = params['base_url'] !== undefined ? params['base_url'] : '';
  const ticket: string = params['ticket'] !== undefined ? params['ticket'] : '';
  if (version !== 1 || ticket.length < 32) {
    throw new Error('这个 QwenPaw 配对码无效或已过期。');
  }
  const pairing: DirectPairing = { baseUrl: normalizeBaseUrl(baseUrl), ticket: ticket };
  return pairing;
}

export function parseManualInput(baseUrlRaw: string, ticketRaw: string): DirectPairing {
  const baseUrl: string = normalizeBaseUrl(baseUrlRaw);
  const ticket: string = ticketRaw.trim();
  if (ticket.length > 0 && ticket.length < 32) {
    throw new Error('配对码太短（至少 32 字符）。若服务未开账号体系，可留空直连。');
  }
  const pairing: DirectPairing = { baseUrl: baseUrl, ticket: ticket };
  return pairing;
}

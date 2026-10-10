/*
 * 协议自检 —— 在鸿蒙真机内验证 RelayCodec.ets 与契约 relay.ts 的逐帧一致性。
 *
 * 向量来源：
 *  1-4. PR #7378 的 relayProtocol.test.ts 四个测试向量（node24 对拍 4/4 PASS）
 *  5-7. canonical 字节向量：由 node24 运行 TS 原版编码后取 hex（含 4 字节大端长度前缀），
 *       ArkTS 编码输出必须逐字节相等
 */

import { encodeRelayFrame, decodeRelayFrame } from './RelayCodec';
import { RelayFrame, RelayFrameHeader } from './RelayCodec';
import { normalizeBaseUrl, hostOf } from './PairingModel';

export interface SelfTestResult {
  name: string;
  pass: boolean;
  detail: string;
}

const DATA_HEX: string =
  '0000007a7b226d65746164617461223a7b22636f6e74656e745f74797065223a22696d6167652f706e67227d2c22726571756573745f6964223a22726571756573742d31222c2273657175656e6365223a332c2273747265616d5f6964223a2273747265616d2d31222c2274797065223a2264617461222c2276223a317d0001706e67';
const HELLO_HEX: string =
  '000000597b226d65746164617461223a7b22636c69656e74223a227177656e7061772d6861726d6f6e79222c22636f6e74726163745f76657273696f6e223a22302e312e30227d2c2274797065223a2268656c6c6f222c2276223a317d';
const PONG_HEX: string = '000000157b2274797065223a22706f6e67222c2276223a317d';

function toHex(u: Uint8Array): string {
  let s: string = '';
  for (let i = 0; i < u.length; i++) {
    const b: string = u[i].toString(16);
    s += b.length === 1 ? `0${b}` : b;
  }
  return s;
}

function dataHeader(): RelayFrameHeader {
  const metadata: Record<string, Object> = { 'content_type': 'image/png' };
  const header: RelayFrameHeader = {
    v: 1,
    type: 'data',
    stream_id: 'stream-1',
    request_id: 'request-1',
    sequence: 3,
    metadata: metadata
  };
  return header;
}

export function runCodecSelfTest(): SelfTestResult[] {
  const results: SelfTestResult[] = [];
  results.push(check('1. data 帧 roundtrip（PR 向量）', () => {
    const payload: Uint8Array = new Uint8Array([0, 1, 112, 110, 103]);
    const frame: RelayFrame = { header: dataHeader(), payload: payload };
    const decoded: RelayFrame = decodeRelayFrame(encodeRelayFrame(frame));
    const meta: Record<string, Object> | undefined = decoded.header.metadata;
    const metaOk: boolean = meta !== undefined && (meta['content_type'] as string) === 'image/png';
    return decoded.header.v === 1 && decoded.header.type === 'data' &&
      decoded.header.stream_id === 'stream-1' && decoded.header.request_id === 'request-1' &&
      decoded.header.sequence === 3 && metaOk &&
      decoded.payload.length === 5 && decoded.payload[0] === 0 && decoded.payload[1] === 1 &&
      decoded.payload[2] === 112 && decoded.payload[3] === 110 && decoded.payload[4] === 103;
  }));

  results.push(check('2. session_event 缺 event_id 被拒（PR 向量）', () => {
    const metadata: Record<string, Object> = { 'session_id': 'sess-9' };
    const header: RelayFrameHeader = {
      v: 1,
      type: 'session_event',
      stream_id: 'stream-2',
      request_id: 'request-2',
      sequence: 7,
      metadata: metadata
    };
    try {
      encodeRelayFrame({ header: header, payload: new Uint8Array(0) });
      return false;
    } catch (e) {
      return (e as Error).message.indexOf('event_id') >= 0;
    }
  }));

  results.push(check('3. open operation 白名单（PR 向量）', () => {
    const okMeta: Record<string, Object> = { 'operation_id': 'message.send', 'schema_version': 1 };
    const okHeader: RelayFrameHeader = {
      v: 1, type: 'open', request_id: 'request-1', stream_id: 'stream-1', metadata: okMeta
    };
    encodeRelayFrame({ header: okHeader, payload: new Uint8Array(0) });
    const badMeta: Record<string, Object> = { 'operation_id': 'http.proxy', 'schema_version': 1 };
    const badHeader: RelayFrameHeader = {
      v: 1, type: 'open', request_id: 'request-1', stream_id: 'stream-1', metadata: badMeta
    };
    try {
      encodeRelayFrame({ header: badHeader, payload: new Uint8Array(0) });
      return false;
    } catch (e) {
      return (e as Error).message.indexOf('operation_id') >= 0;
    }
  }));

  results.push(check('4. 截断输入被拒（PR 向量）', () => {
    try {
      decodeRelayFrame(new Uint8Array([0, 0, 0, 20, 123, 125]));
      return false;
    } catch (e) {
      return (e as Error).message.indexOf('truncated') >= 0;
    }
  }));

  results.push(check('5. canonical hello 逐字节', () => {
    const metadata: Record<string, Object> = { 'client': 'qwenpaw-harmony', 'contract_version': '0.1.0' };
    const header: RelayFrameHeader = { v: 1, type: 'hello', metadata: metadata };
    return toHex(encodeRelayFrame({ header: header, payload: new Uint8Array(0) })) === HELLO_HEX;
  }));

  results.push(check('6. canonical pong 逐字节', () => {
    const header: RelayFrameHeader = { v: 1, type: 'pong' };
    return toHex(encodeRelayFrame({ header: header, payload: new Uint8Array(0) })) === PONG_HEX;
  }));

  results.push(check('7. canonical data 逐字节', () => {
    const payload: Uint8Array = new Uint8Array([0, 1, 112, 110, 103]);
    return toHex(encodeRelayFrame({ header: dataHeader(), payload: payload })) === DATA_HEX;
  }));

  // 地址解析（对齐 7378 api/pairing.ts 的标准 URL 解析：IPv4 / IPv6 / 域名 / 端口）
  results.push(check('8. 地址：裸 host:port 补 http', () => {
    return normalizeBaseUrl('192.168.1.10:8088') === 'http://192.168.1.10:8088';
  }));
  results.push(check('9. 地址：域名 + https + 端口', () => {
    return normalizeBaseUrl('https://paw.example.com:8443') === 'https://paw.example.com:8443';
  }));
  results.push(check('10. 地址：IPv6 保留方括号', () => {
    return normalizeBaseUrl('http://[fe80::1]:8088') === 'http://[fe80::1]:8088';
  }));
  results.push(check('11. 地址：hostOf 提取主机（IPv6 含端口）', () => {
    return hostOf('http://[fe80::1]:8088') === '[fe80::1]:8088';
  }));
  results.push(check('12. 地址：带凭据被拒', () => {
    try {
      normalizeBaseUrl('http://u:p@nas.local:8088');
      return false;
    } catch (e) {
      return true;
    }
  }));

  return results;
}

function check(name: string, fn: () => boolean): SelfTestResult {
  try {
    const ok: boolean = fn();
    const r: SelfTestResult = { name: name, pass: ok, detail: ok ? 'ok' : 'assertion failed' };
    return r;
  } catch (e) {
    const r: SelfTestResult = { name: name, pass: false, detail: (e as Error).message };
    return r;
  }
}

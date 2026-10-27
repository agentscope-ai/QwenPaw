/*
 * napi_init.cpp —— atls 的 NAPI 胶水层（ArkTS ⇄ atls_http.c）
 *
 * 导出（类型声明见 entry/src/main/cpp/types/libatls/Index.d.ts）：
 *   request(opts)              → Promise<AtlsResponse>  完整请求（含 3xx 跟跳 ≤20）
 *   requestStream(opts)        → Promise<{status,headers,setCookies}>  流式请求
 *      （onHeaders/onData 在工作线程事件序列里经 tsfn 回 JS 线程派发，
 *        块 ≤8KB 帧边界无关；中止用 cancelRequest(cancelId)，onData 返回值忽略）
 *   tlsProbe(host, port, ms)   → Promise<AtlsProbeResult>  诊断页握手取证
 *   version()                  → string（实际 TLS 栈版本，结案证据用）
 *   beginCancelSlot()          → number（在途取消槽 id）
 *   cancelRequest(id)          → void（置位取消；C 侧轮询粒度 ≤200ms）
 *
 * 错误协议：传输层失败一律 reject Error("atls:<kind>: <detail>")，
 * kind 为 atls_kind_name 稳定串；ArkTS classifyError 按该前缀做确定性
 * kind 分支（前缀与 kind 名两侧共用 atls_http.h 一份定义）。
 *
 * 线程模型：I/O 全在工作线程（std::thread per request）；结果经模块级
 * threadsafe function 回 JS 线程 resolve/reject。取消槽：beginCancelSlot
 * 分配、对应请求的投递回调（JS 线程）回收；cancelRequest 找不到槽 =
 * 请求已结束 = no-op，天然安全。
 */
#include <napi/native_api.h>

#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include "atls_http.h"

namespace {

// ---------- 在途取消槽 ----------

std::mutex g_slotMtx;
/* id → 槽位（unique_ptr 保指针稳定：unordered_map rehash 只搬指针不搬对象） */
std::unordered_map<int, std::unique_ptr<volatile int>> g_slots;
int g_nextSlotId = 1;

/* ---------- 流式请求的 JS 侧上下文（JS 线程建/析，worker 仅以 ud 传递） ---------- */

struct StreamJsCtx {
  napi_ref onHeadersRef = nullptr; /* 可选 */
  napi_ref onDataRef = nullptr; /* 必填 */
  napi_deferred deferred = nullptr;
  int slotId = -1;
};

/* ---------- 投递载荷（worker 线程构造，JS 线程消费后释放） ---------- */

enum class Tag { Request, Probe, StreamHeaders, StreamData, StreamEnd };

struct Payload {
  Tag tag = Tag::Request;
  StreamJsCtx *ctx = nullptr; /* 流式载荷持有；StreamEnd 负责析构 */
  napi_deferred deferred = nullptr;
  int slotId = -1; /* ≥0 时投递后回收该槽 */
  bool ok = false;
  bool isProbe = false;
  /* request 成功面 */
  int status = 0;
  std::vector<std::pair<std::string, std::string>> headers; /* 小写 key，重复键后者胜 */
  std::vector<std::string> setCookies;
  std::vector<unsigned char> body;
  /* probe 成功面 */
  std::string protocol;
  std::string cipher;
  /* 失败面 */
  std::string errMsg;
};

napi_threadsafe_function g_tsfn = nullptr;

/* 构造 {status, headers, setCookies} 普通对象（流式头事件与收尾 resolve 共用） */
napi_value MakeInfoObject(napi_env env, int status,
                          const std::vector<std::pair<std::string, std::string>> &headers,
                          const std::vector<std::string> &setCookies) {
  napi_value result;
  if (napi_create_object(env, &result) != napi_ok) {
    return nullptr;
  }
  napi_value v;
  napi_create_int32(env, status, &v);
  napi_set_named_property(env, result, "status", v);
  napi_value hobj;
  napi_create_object(env, &hobj);
  for (const auto &kv : headers) {
    napi_value vk, vv;
    if (napi_create_string_utf8(env, kv.first.c_str(), NAPI_AUTO_LENGTH, &vk) == napi_ok &&
        napi_create_string_utf8(env, kv.second.c_str(), NAPI_AUTO_LENGTH, &vv) == napi_ok) {
      napi_set_property(env, hobj, vk, vv);
    }
  }
  napi_set_named_property(env, result, "headers", hobj);
  napi_value arr;
  napi_create_array(env, &arr);
  for (size_t i = 0; i < setCookies.size(); i++) {
    napi_value vc;
    if (napi_create_string_utf8(env, setCookies[i].c_str(), NAPI_AUTO_LENGTH, &vc) == napi_ok) {
      napi_set_element(env, arr, static_cast<uint32_t>(i), vc);
    }
  }
  napi_set_named_property(env, result, "setCookies", arr);
  return result;
}

/* JS 线程：流式载荷（头事件 / 数据块 / 收尾）。StreamEnd 析构 ctx 并回收取消槽 */
void DeliverStream(napi_env env, Payload *p, int slotId) {
  StreamJsCtx *ctx = p->ctx;
  if (p->tag == Tag::StreamHeaders) {
    if (ctx && ctx->onHeadersRef) {
      napi_value fn, info = MakeInfoObject(env, p->status, p->headers, p->setCookies);
      if (info != nullptr && napi_get_reference_value(env, ctx->onHeadersRef, &fn) == napi_ok) {
        napi_value argv[1] = {info};
        napi_value rv;
        napi_call_function(env, nullptr, fn, 1, argv, &rv); /* 返回值忽略 */
      }
    }
  } else if (p->tag == Tag::StreamData) {
    if (ctx && ctx->onDataRef && !p->body.empty()) {
      void *abData = nullptr;
      napi_value buf;
      if (napi_create_arraybuffer(env, p->body.size(), &abData, &buf) == napi_ok) {
        std::memcpy(abData, p->body.data(), p->body.size());
        napi_value fn, rv;
        if (napi_get_reference_value(env, ctx->onDataRef, &fn) == napi_ok) {
          napi_value argv[1] = {buf};
          napi_call_function(env, nullptr, fn, 1, argv, &rv); /* 返回值忽略（中止走取消槽） */
        }
      }
    }
  } else if (p->tag == Tag::StreamEnd) {
    if (ctx) {
      if (p->ok) {
        napi_value result = MakeInfoObject(env, p->status, p->headers, p->setCookies);
        if (result != nullptr) {
          napi_resolve_deferred(env, ctx->deferred, result);
        }
      } else {
        napi_value msgStr;
        if (napi_create_string_utf8(env, p->errMsg.c_str(), NAPI_AUTO_LENGTH, &msgStr) == napi_ok) {
          napi_value errVal;
          if (napi_create_error(env, nullptr, msgStr, &errVal) == napi_ok) {
            napi_reject_deferred(env, ctx->deferred, errVal);
          }
        }
      }
      napi_delete_reference(env, ctx->onDataRef);
      if (ctx->onHeadersRef) {
        napi_delete_reference(env, ctx->onHeadersRef);
      }
      delete ctx;
    }
  }
  delete p;
  if (slotId >= 0) {
    std::lock_guard<std::mutex> lk(g_slotMtx);
    g_slots.erase(slotId);
  }
}

/* JS 线程：resolve/reject 并回收取消槽（与 cancelRequest 同线程无竞态） */
void Deliver(napi_env env, napi_value /*js_callback*/, void * /*context*/, void *data) {
  Payload *p = static_cast<Payload *>(data);
  const int slotId = p->slotId;
  if (p->tag == Tag::StreamHeaders || p->tag == Tag::StreamData || p->tag == Tag::StreamEnd) {
    DeliverStream(env, p, slotId);
    return;
  }
  napi_value result;
  if (p->ok) {
    if (napi_create_object(env, &result) != napi_ok) {
      delete p;
      return;
    }
    if (p->isProbe) {
      napi_value v;
      napi_create_string_utf8(env, p->protocol.c_str(), NAPI_AUTO_LENGTH, &v);
      napi_set_named_property(env, result, "protocol", v);
      napi_create_string_utf8(env, p->cipher.c_str(), NAPI_AUTO_LENGTH, &v);
      napi_set_named_property(env, result, "cipher", v);
    } else {
      napi_value v;
      napi_create_int32(env, p->status, &v);
      napi_set_named_property(env, result, "status", v);
      napi_value hobj;
      napi_create_object(env, &hobj);
      for (const auto &kv : p->headers) {
        napi_value vk, vv;
        if (napi_create_string_utf8(env, kv.first.c_str(), NAPI_AUTO_LENGTH, &vk) == napi_ok &&
            napi_create_string_utf8(env, kv.second.c_str(), NAPI_AUTO_LENGTH, &vv) == napi_ok) {
          napi_set_property(env, hobj, vk, vv);
        }
      }
      napi_set_named_property(env, result, "headers", hobj);
      napi_value arr;
      napi_create_array(env, &arr);
      for (size_t i = 0; i < p->setCookies.size(); i++) {
        napi_value v;
        if (napi_create_string_utf8(env, p->setCookies[i].c_str(), NAPI_AUTO_LENGTH, &v) == napi_ok) {
          napi_set_element(env, arr, static_cast<uint32_t>(i), v);
        }
      }
      napi_set_named_property(env, result, "setCookies", arr);
      napi_value bodyVal;
      if (p->body.empty()) {
        napi_get_null(env, &bodyVal);
      } else {
        void *abData = nullptr;
        if (napi_create_arraybuffer(env, p->body.size(), &abData, &bodyVal) == napi_ok) {
          std::memcpy(abData, p->body.data(), p->body.size());
        } else {
          napi_get_null(env, &bodyVal);
        }
      }
      napi_set_named_property(env, result, "body", bodyVal);
    }
    napi_resolve_deferred(env, p->deferred, result);
  } else {
    /* OHOS napi_create_error 的 msg 参数是 napi_value（先建字符串） */
    napi_value msgStr;
    if (napi_create_string_utf8(env, p->errMsg.c_str(), NAPI_AUTO_LENGTH, &msgStr) == napi_ok) {
      napi_value errVal;
      if (napi_create_error(env, nullptr, msgStr, &errVal) == napi_ok) {
        napi_reject_deferred(env, p->deferred, errVal);
      }
    }
  }
  delete p;
  if (slotId >= 0) {
    std::lock_guard<std::mutex> lk(g_slotMtx);
    g_slots.erase(slotId);
  }
}

/* ---------- request ---------- */

struct ReqArgs {
  std::string url;
  std::string method;
  std::vector<std::string> headerKeys;
  std::vector<std::string> headerValues;
  std::vector<unsigned char> body;
  int connectMs = 3000;
  int readMs = 30000;
  int slotId = -1;
  volatile int *cancel = nullptr; /* 指向槽内位，生命周期覆盖 atls_request 全程 */
  napi_deferred deferred = nullptr;
};

void ReqWorker(ReqArgs *a) {
  Payload *p = new Payload();
  p->deferred = a->deferred;
  p->slotId = a->slotId;
  {
    std::vector<const char *> keys;
    std::vector<const char *> values;
    keys.reserve(a->headerKeys.size());
    values.reserve(a->headerValues.size());
    for (const auto &s : a->headerKeys) {
      keys.push_back(s.c_str());
    }
    for (const auto &s : a->headerValues) {
      values.push_back(s.c_str());
    }
    atls_request_opts opts;
    std::memset(&opts, 0, sizeof(opts));
    opts.url = a->url.c_str();
    opts.method = a->method.c_str();
    opts.header_keys = keys.empty() ? nullptr : keys.data();
    opts.header_values = values.empty() ? nullptr : values.data();
    opts.header_count = keys.size();
    opts.body = a->body.empty() ? nullptr : a->body.data();
    opts.body_len = a->body.size();
    opts.connect_timeout_ms = a->connectMs;
    opts.read_timeout_ms = a->readMs;
    opts.cancel = a->cancel;
    atls_response resp;
    std::memset(&resp, 0, sizeof(resp));
    const int rc = atls_request(&opts, &resp);
    if (rc == 0) {
      p->ok = true;
      p->status = resp.status;
      for (size_t i = 0; i < resp.header_count; i++) {
        p->headers.emplace_back(resp.headers[i * 2], resp.headers[i * 2 + 1]);
      }
      for (size_t i = 0; i < resp.set_cookie_count; i++) {
        p->setCookies.push_back(resp.set_cookies[i]);
      }
      if (resp.body != nullptr && resp.body_len > 0) {
        p->body.assign(resp.body, resp.body + resp.body_len);
      }
    } else {
      char msg[512];
      std::snprintf(msg, sizeof(msg), "atls:%s: %s", atls_kind_name(resp.err), resp.err_msg);
      p->errMsg = msg;
    }
    atls_response_free(&resp);
  }
  napi_acquire_threadsafe_function(g_tsfn);
  if (napi_call_threadsafe_function(g_tsfn, p, napi_tsfn_nonblocking) != napi_ok) {
    delete p;
  }
  napi_release_threadsafe_function(g_tsfn, napi_tsfn_release);
  delete a;
}

/* ---------- tlsProbe ---------- */

struct ProbeArgs {
  std::string host;
  int port = 0;
  int timeoutMs = 0;
  napi_deferred deferred = nullptr;
};

void ProbeWorker(ProbeArgs *a) {
  Payload *p = new Payload();
  p->deferred = a->deferred;
  p->isProbe = true;
  char proto[64] = {0};
  char cipher[64] = {0};
  char err[256] = {0};
  const int rc = atls_tls_probe(a->host.c_str(), a->port, a->timeoutMs, proto, sizeof(proto),
                                cipher, sizeof(cipher), err, sizeof(err));
  if (rc == 0) {
    p->ok = true;
    p->protocol = proto;
    p->cipher = cipher;
  } else {
    /* atls_tls_probe 的 err 已带 "atls:<kind>: <detail>" 前缀 */
    p->errMsg = err;
  }
  napi_acquire_threadsafe_function(g_tsfn);
  if (napi_call_threadsafe_function(g_tsfn, p, napi_tsfn_nonblocking) != napi_ok) {
    delete p;
  }
  napi_release_threadsafe_function(g_tsfn, napi_tsfn_release);
  delete a;
}

/* ---------- requestStream ---------- */


/* worker 线程：最终响应的头事件。投递头载荷 + 顺带捕获到 args 供收尾 resolve */
struct StreamArgs {
  std::string url;
  std::string method;
  std::vector<std::string> headerKeys;
  std::vector<std::string> headerValues;
  std::vector<unsigned char> body;
  int connectMs = 3000;
  int readMs = 30000;
  int slotId = -1;
  volatile int *cancel = nullptr;
  StreamJsCtx *ctx = nullptr;
  /* on_headers 捕获的最终响应头（仅 worker 写、worker 读） */
  int finalStatus = 0;
  std::vector<std::pair<std::string, std::string>> finalHeaders;
  std::vector<std::string> finalSetCookies;
};

static int COnHeaders(void *ud, int status, char **headers, size_t header_count,
                      char **set_cookies, size_t set_cookie_count) {
  StreamArgs *a = static_cast<StreamArgs *>(ud);
  std::vector<std::pair<std::string, std::string>> hs;
  std::vector<std::string> sc;
  for (size_t i = 0; i < header_count; i++) {
    hs.emplace_back(headers[i * 2], headers[i * 2 + 1]);
  }
  for (size_t i = 0; i < set_cookie_count; i++) {
    sc.push_back(set_cookies[i]);
  }
  Payload *p = new Payload();
  p->tag = Tag::StreamHeaders;
  p->ctx = a->ctx;
  p->status = status;
  p->headers = std::move(hs);
  p->setCookies = std::move(sc);
  napi_acquire_threadsafe_function(g_tsfn);
  if (napi_call_threadsafe_function(g_tsfn, p, napi_tsfn_nonblocking) != napi_ok) {
    delete p;
  }
  napi_release_threadsafe_function(g_tsfn, napi_tsfn_release);
  /* 捕获到 worker 本地，供最终 StreamEnd 载荷使用（JS 线程不读本结构数据面） */
  a->finalStatus = status;
  a->finalHeaders = hs;
  a->finalSetCookies = sc;
  return 0;
}

/* worker 线程：数据块（≤8KB，帧边界无关） */
static int COnData(void *ud, const unsigned char *data, size_t len) {
  StreamArgs *a = static_cast<StreamArgs *>(ud);
  if (len == 0) {
    return 0;
  }
  Payload *p = new Payload();
  p->tag = Tag::StreamData;
  p->ctx = a->ctx;
  p->body.assign(data, data + len);
  napi_acquire_threadsafe_function(g_tsfn);
  if (napi_call_threadsafe_function(g_tsfn, p, napi_tsfn_nonblocking) != napi_ok) {
    delete p;
  }
  napi_release_threadsafe_function(g_tsfn, napi_tsfn_release);
  return 0;
}

void StreamWorker(StreamArgs *a) {
  atls_stream_cbs cbs;
  std::memset(&cbs, 0, sizeof(cbs));
  cbs.ud = a;
  cbs.on_headers = COnHeaders;
  cbs.on_data = COnData;
  atls_err err = ATLS_ERR_NONE;
  char errMsg[256] = {0};
  std::vector<const char *> keys;
  std::vector<const char *> values;
  keys.reserve(a->headerKeys.size());
  values.reserve(a->headerValues.size());
  for (const auto &s : a->headerKeys) {
    keys.push_back(s.c_str());
  }
  for (const auto &s : a->headerValues) {
    values.push_back(s.c_str());
  }
  atls_request_opts opts;
  std::memset(&opts, 0, sizeof(opts));
  opts.url = a->url.c_str();
  opts.method = a->method.c_str();
  opts.header_keys = keys.empty() ? nullptr : keys.data();
  opts.header_values = values.empty() ? nullptr : values.data();
  opts.header_count = keys.size();
  opts.body = a->body.empty() ? nullptr : a->body.data();
  opts.body_len = a->body.size();
  opts.connect_timeout_ms = a->connectMs;
  opts.read_timeout_ms = a->readMs;
  opts.cancel = a->cancel;
  const int rc = atls_request_stream(&opts, &cbs, &err, errMsg, sizeof(errMsg));
  Payload *p = new Payload();
  p->tag = Tag::StreamEnd;
  p->ctx = a->ctx;
  p->slotId = a->slotId;
  if (rc == 0) {
    p->ok = true;
    p->status = a->finalStatus;
    p->headers = a->finalHeaders;
    p->setCookies = a->finalSetCookies;
  } else {
    char msg[512];
    std::snprintf(msg, sizeof(msg), "atls:%s: %s", atls_kind_name(err), errMsg);
    p->errMsg = msg;
  }
  napi_acquire_threadsafe_function(g_tsfn);
  if (napi_call_threadsafe_function(g_tsfn, p, napi_tsfn_nonblocking) != napi_ok) {
    delete p;
  }
  napi_release_threadsafe_function(g_tsfn, napi_tsfn_release);
  delete a;
}

/* ---------- JS 参数读取小工具 ---------- */

std::string ReadString(napi_env env, napi_value v) {
  size_t len = 0;
  if (napi_get_value_string_utf8(env, v, nullptr, 0, &len) != napi_ok) {
    return "";
  }
  std::string s(len, '\0');
  if (len > 0 && napi_get_value_string_utf8(env, v, &s[0], len + 1, &len) != napi_ok) {
    return "";
  }
  s.resize(len);
  return s;
}

/* request/requestStream 共用的 opts 读取（url/method/headers/body/connectMs/readMs） */
void readCommonOpts(napi_env env, const napi_value opts, ReqArgs *a) {
  napi_value v;
  napi_valuetype t;
  if (napi_get_named_property(env, opts, "url", &v) == napi_ok &&
      napi_typeof(env, v, &t) == napi_ok && t == napi_string) {
    a->url = ReadString(env, v);
  }
  if (napi_get_named_property(env, opts, "method", &v) == napi_ok &&
      napi_typeof(env, v, &t) == napi_ok && t == napi_string) {
    a->method = ReadString(env, v);
  }
  if (napi_get_named_property(env, opts, "headers", &v) == napi_ok &&
      napi_typeof(env, v, &t) == napi_ok && t == napi_object) {
    napi_value names;
    if (napi_get_property_names(env, v, &names) == napi_ok) {
      uint32_t n = 0;
      napi_get_array_length(env, names, &n);
      for (uint32_t i = 0; i < n; i++) {
        napi_value nameV, valV;
        if (napi_get_element(env, names, i, &nameV) != napi_ok) {
          continue;
        }
        if (napi_get_property(env, v, nameV, &valV) != napi_ok) {
          continue;
        }
        a->headerKeys.push_back(ReadString(env, nameV));
        a->headerValues.push_back(ReadString(env, valV));
      }
    }
  }
  if (napi_get_named_property(env, opts, "bodyText", &v) == napi_ok &&
      napi_typeof(env, v, &t) == napi_ok && t == napi_string) {
    const std::string s = ReadString(env, v);
    a->body.assign(s.begin(), s.end());
  }
  /* OHOS napi_valuetype 无 arraybuffer 成员（归为 napi_object），须用 is_arraybuffer 判 */
  bool isAb = false;
  if (napi_get_named_property(env, opts, "bodyBytes", &v) == napi_ok &&
      napi_is_arraybuffer(env, v, &isAb) == napi_ok && isAb) {
    void *data = nullptr;
    size_t len = 0;
    if (napi_get_arraybuffer_info(env, v, &data, &len) == napi_ok && data != nullptr && len > 0) {
      const auto *b = static_cast<const unsigned char *>(data);
      a->body.assign(b, b + len);
    }
  }
  double d = 0;
  if (napi_get_named_property(env, opts, "connectMs", &v) == napi_ok &&
      napi_get_value_double(env, v, &d) == napi_ok) {
    a->connectMs = static_cast<int>(d);
  }
  if (napi_get_named_property(env, opts, "readMs", &v) == napi_ok &&
      napi_get_value_double(env, v, &d) == napi_ok) {
    a->readMs = static_cast<int>(d);
  }
}

}  // namespace

/* ---------- 导出函数 ---------- */

napi_value JsRequest(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  if (argc < 1) {
    napi_throw_type_error(env, nullptr, "atls.request(opts) requires opts");
    return nullptr;
  }
  const napi_value opts = argv[0];
  ReqArgs *a = new ReqArgs();
  readCommonOpts(env, opts, a);
  {
    napi_value v;
    double d = 0;
    if (napi_get_named_property(env, opts, "cancelId", &v) == napi_ok &&
        napi_get_value_double(env, v, &d) == napi_ok) {
      a->slotId = static_cast<int>(d);
    }
  }
  if (a->slotId >= 0) {
    /* 槽只会被本请求的投递回调回收（在 atls_request 返回之后），
     * 故裸指针在整个 worker 生命周期内有效 */
    std::lock_guard<std::mutex> lk(g_slotMtx);
    const auto it = g_slots.find(a->slotId);
    a->cancel = it != g_slots.end() ? it->second.get() : nullptr;
  }
  napi_value promise;
  napi_deferred deferred;
  if (napi_create_promise(env, &deferred, &promise) != napi_ok) {
    delete a;
    return nullptr;
  }
  a->deferred = deferred;
  std::thread(ReqWorker, a).detach();
  return promise;
}

napi_value JsRequestStream(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  if (argc < 1) {
    napi_throw_type_error(env, nullptr, "atls.requestStream(opts) requires opts");
    return nullptr;
  }
  const napi_value opts = argv[0];
  StreamArgs *a = new StreamArgs();
  {
    /* 共用字段读进 ReqArgs（字段面与 StreamArgs 一致），cancelId 单独处理 */
    ReqArgs r;
    readCommonOpts(env, opts, &r);
    a->url = std::move(r.url);
    a->method = std::move(r.method);
    a->headerKeys = std::move(r.headerKeys);
    a->headerValues = std::move(r.headerValues);
    a->body = std::move(r.body);
    a->connectMs = r.connectMs;
    a->readMs = r.readMs;
    napi_value v;
    double d = 0;
    if (napi_get_named_property(env, opts, "cancelId", &v) == napi_ok &&
        napi_get_value_double(env, v, &d) == napi_ok) {
      a->slotId = static_cast<int>(d);
    }
  }
  napi_value v;
  napi_valuetype t;
  if (napi_get_named_property(env, opts, "onData", &v) != napi_ok ||
      napi_typeof(env, v, &t) != napi_ok || t != napi_function) {
    delete a;
    napi_throw_type_error(env, nullptr, "atls.requestStream(opts) requires onData function");
    return nullptr;
  }
  const napi_value onData = v;
  napi_value onHeadersV = nullptr;
  bool hasOnHeaders = false;
  if (napi_get_named_property(env, opts, "onHeaders", &v) == napi_ok &&
      napi_typeof(env, v, &t) == napi_ok && t == napi_function) {
    onHeadersV = v;
    hasOnHeaders = true;
  }
  StreamJsCtx *ctx = new StreamJsCtx();
  if (napi_create_reference(env, onData, 1, &ctx->onDataRef) != napi_ok ||
      (hasOnHeaders && napi_create_reference(env, onHeadersV, 1, &ctx->onHeadersRef) != napi_ok)) {
    if (ctx->onDataRef) {
      napi_delete_reference(env, ctx->onDataRef);
    }
    if (ctx->onHeadersRef) {
      napi_delete_reference(env, ctx->onHeadersRef);
    }
    delete ctx;
    delete a;
    return nullptr;
  }
  if (a->slotId >= 0) {
    std::lock_guard<std::mutex> lk(g_slotMtx);
    const auto it = g_slots.find(a->slotId);
    a->cancel = it != g_slots.end() ? it->second.get() : nullptr;
  }
  napi_value promise;
  napi_deferred deferred;
  if (napi_create_promise(env, &deferred, &promise) != napi_ok) {
    napi_delete_reference(env, ctx->onDataRef);
    if (ctx->onHeadersRef) {
      napi_delete_reference(env, ctx->onHeadersRef);
    }
    delete ctx;
    delete a;
    return nullptr;
  }
  ctx->deferred = deferred;
  a->ctx = ctx;
  std::thread(StreamWorker, a).detach();
  return promise;
}

napi_value JsTlsProbe(napi_env env, napi_callback_info info) {
  size_t argc = 3;
  napi_value argv[3];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  if (argc < 3) {
    napi_throw_type_error(env, nullptr, "atls.tlsProbe(host, port, timeoutMs) requires 3 args");
    return nullptr;
  }
  double d = 0;
  ProbeArgs *a = new ProbeArgs();
  a->host = ReadString(env, argv[0]);
  if (napi_get_value_double(env, argv[1], &d) != napi_ok) {
    delete a;
    return nullptr;
  }
  a->port = static_cast<int>(d);
  if (napi_get_value_double(env, argv[2], &d) != napi_ok) {
    delete a;
    return nullptr;
  }
  a->timeoutMs = static_cast<int>(d);
  napi_value promise;
  napi_deferred deferred;
  if (napi_create_promise(env, &deferred, &promise) != napi_ok) {
    delete a;
    return nullptr;
  }
  a->deferred = deferred;
  std::thread(ProbeWorker, a).detach();
  return promise;
}

napi_value JsVersion(napi_env env, napi_callback_info /*info*/) {
  napi_value v;
  napi_create_string_utf8(env, atls_version_string(), NAPI_AUTO_LENGTH, &v);
  return v;
}

napi_value JsBeginCancelSlot(napi_env env, napi_callback_info /*info*/) {
  int id = 0;
  {
    std::lock_guard<std::mutex> lk(g_slotMtx);
    id = g_nextSlotId++;
    g_slots[id] = std::unique_ptr<volatile int>(new volatile int(0));
  }
  napi_value v;
  napi_create_int32(env, id, &v);
  return v;
}

napi_value JsCancelRequest(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  if (argc >= 1) {
    int32_t id = 0;
    if (napi_get_value_int32(env, argv[0], &id) == napi_ok) {
      std::lock_guard<std::mutex> lk(g_slotMtx);
      const auto it = g_slots.find(id);
      if (it != g_slots.end()) {
        *it->second = 1;
      }
    }
  }
  return nullptr;
}

static napi_value Init(napi_env env, napi_value exports) {
  napi_value resName;
  napi_create_string_utf8(env, "atls-delivery", NAPI_AUTO_LENGTH, &resName);
  /* 模块级 threadsafe function：JS 线程持初始引用常驻进程生命周期，
   * worker 侧每次投递前 acquire、投递后 release，永不 finalize */
  if (napi_create_threadsafe_function(env, nullptr, nullptr, resName, 0, 1, nullptr, nullptr,
                                      nullptr, &Deliver, &g_tsfn) != napi_ok) {
    napi_throw_error(env, nullptr, "atls: failed to create threadsafe function");
    return nullptr;
  }
  napi_property_descriptor desc[] = {
      {"request", nullptr, JsRequest, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"requestStream", nullptr, JsRequestStream, nullptr, nullptr, nullptr, napi_default,
       nullptr},
      {"tlsProbe", nullptr, JsTlsProbe, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"version", nullptr, JsVersion, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"beginCancelSlot", nullptr, JsBeginCancelSlot, nullptr, nullptr, nullptr, napi_default,
       nullptr},
      {"cancelRequest", nullptr, JsCancelRequest, nullptr, nullptr, nullptr, napi_default,
       nullptr},
  };
  napi_define_properties(env, exports, 6, desc);
  return exports;
}

NAPI_MODULE(atls, Init)

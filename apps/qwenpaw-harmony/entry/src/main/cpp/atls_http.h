/*
 * atls_http.h —— 自研 HTTP/1.1 传输层（OpenSSL 静态链接）
 *
 * 背景：HarmonyOS 系统 http 组件的 TLS 栈（libcurl 8.8.0 + OpenSSL 3.0.9，
 * ClientHello 携带 h2 ALPN 与 CBC/DHE 传统套件）在特定链路被中间设备按指纹
 * 重置；本模块以自编译 OpenSSL 3.5 拨外网，语义对齐 Python 插件 httpx：
 * 3xx 跟跳 ≤20、set-cookie 原样捕获、Connection: close 单请求单连接。
 *
 * TLS 规格（命中"现代栈"最低要求）：
 *   min=TLS1.2 且**不设 max**——TLS1.3 默认套件与默认分组完整保留；
 *   TLS≤1.2 套件白名单仅 ECDHE+AEAD（无 CBC/DHE/RSA 密钥交换；该白名单
 *   只作用于 TLS1.2 及以下，TLS1.3 套件是独立 API、不受它约束）；
 *   ALPN 仅 http/1.1（绝不 h2）；SNI + 主机名/IP 校验（IP 不发 SNI）；
 *   CA 信任 = 内置 Mozilla 根证书包，不依赖设备 CA 路径。
 *
 * 纯 C 实现（宿主 glibc / 设备 musl 通用）；NAPI 胶水见 napi_init.cpp。
 */
#ifndef ATLS_HTTP_H
#define ATLS_HTTP_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 传输层错误分类（与 ArkTS classifyError 文案分支一一对应） */
typedef enum {
  ATLS_ERR_NONE = 0,
  ATLS_ERR_CONNECT_TIMEOUT, /* 建连超时 */
  ATLS_ERR_READ_TIMEOUT,    /* 读响应超时（长轮询读窗口耗尽） */
  ATLS_ERR_DNS,             /* 域名解析失败 */
  ATLS_ERR_REFUSED,         /* 连接被拒 */
  ATLS_ERR_TLS_VERIFY,      /* 证书校验失败（自签/过期/链不完整） */
  ATLS_ERR_TLS,             /* TLS 握手失败（含握手阶段被 RST） */
  ATLS_ERR_IO,              /* 传输中断（读中途 EIO/EOF/被重置） */
  ATLS_ERR_PROTOCOL,        /* 响应格式非法 / 跟跳超限 */
  ATLS_ERR_CANCELLED,       /* 调用方取消 */
  ATLS_ERR_OOM,             /* 内存/尺寸保护触发 */
  ATLS_ERR_BAD_URL          /* URL 不可解析 */
} atls_err;

/* 错误分类 → 稳定 kind 串（NAPI 错误消息前缀 "atls:<kind>: <detail>" 与
 * ArkTS atlsErrorToTransport 的映射共用这一份定义） */
const char *atls_kind_name(atls_err kind);

typedef struct {
  const char *url;
  const char *method; /* GET/POST/PUT/DELETE/HEAD/PATCH */
  const char *const *header_keys;
  const char *const *header_values;
  size_t header_count;
  const unsigned char *body;
  size_t body_len;
  int connect_timeout_ms;
  int read_timeout_ms;
  /* 可选取消位：非 0 时中止（轮询粒度 ≤200ms） */
  volatile int *cancel;
} atls_request_opts;

typedef struct {
  int status;
  unsigned char *body; /* malloc；可为 NULL（len 0） */
  size_t body_len;
  /* 响应头（小写 key；重复头保留多条，set-cookie 除外）：
   * 交错存储 headers[2i]=key、headers[2i+1]=value；header_count = 键值对数 */
  char **headers;
  size_t header_count;
  /* 全部 Set-Cookie 头原值（多条各占一项） */
  char **set_cookies;
  size_t set_cookie_count;
  atls_err err;
  char err_msg[256];
} atls_response;

/* 执行一次完整 HTTP 请求（含 3xx 跟跳）。
 * 0 = 收到 HTTP 响应（含 4xx/5xx，status 见 out->status）；
 * -1 = 传输层失败（out->err / out->err_msg）。
 * 成功后须 atls_response_free 释放。 */
int atls_request(const atls_request_opts *opts, atls_response *out);

void atls_response_free(atls_response *r);

/* 流式响应回调（SSE 等分块交付）：
 * on_headers 在读完状态行+头之后、首个数据块之前调用一次；
 * on_data 按传输分块推送响应体（块 ≤8KB，帧边界无关——SSE 行帧由上层解析器重建）。
 * 两个回调都在 atls_request_stream 的工作线程上执行，不得阻塞；
 * 返回非 0 = 交付方要求中止（整体判 ATLS_ERR_CANCELLED）。 */
typedef struct {
  void *ud;
  int (*on_headers)(void *ud, int status, char **headers, size_t header_count,
                    char **set_cookies, size_t set_cookie_count);
  int (*on_data)(void *ud, const unsigned char *data, size_t len);
} atls_stream_cbs;

/* 执行流式 HTTP 请求（含 3xx 跟跳 ≤20：3xx 响应体读完丢弃后换址，
 * 只有最终响应才触发 on_headers/on_data；1xx 中间头丢弃）。
 * 0 = 流正常完结（对端干净关闭 / Content-Length 读完）；
 * -1 = 传输层失败（out_err / err_msg_out）。
 * opts->cancel 在每次读等待片（≤200ms）检查，中止同样判 CANCELLED。 */
int atls_request_stream(const atls_request_opts *opts, const atls_stream_cbs *cbs,
                        atls_err *out_err, char *err_msg_out, size_t err_msg_cap);

/* TLS 握手探测（诊断页用：不交换 HTTP，握手成功即回）
 * 0 = 握手成功（protocol_out/cipher_out 填协商结果）；-1 = 失败（err_msg_out） */
int atls_tls_probe(const char *host, int port, int timeout_ms, char *protocol_out,
                   size_t protocol_cap, char *cipher_out, size_t cipher_cap,
                   char *err_msg_out, size_t err_msg_cap);

/* 实际在用的 TLS 库版本（自检/诊断取证："实际使用的库与版本"） */
const char *atls_version_string(void);

#ifdef __cplusplus
}
#endif
#endif /* ATLS_HTTP_H */

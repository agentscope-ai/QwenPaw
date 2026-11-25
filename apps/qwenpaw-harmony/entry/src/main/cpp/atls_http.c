/*
 * atls_http.c —— 自研 HTTP/1.1 传输层实现（OpenSSL 3.5 静态链接）
 *
 * 结构（单一请求生命周期，无全局状态、无连接池——Connection: close 口径）：
 *   parse_url → for hop ≤20 { tcp_connect → [tls_handshake] → send_request
 *                   → read_response → [3xx? 解析 Location 换址] }
 *
 * 超时/取消：所有阻塞点统一走 poll_wait（单片 ≤200ms 轮询 + 绝对截止时刻），
 * 取消位在每个轮询片检查——长轮询取消延迟 ≤200ms。
 *
 * ClientHello 规格（命中"现代栈"最低要求）：
 *   min=TLS1.2，不设 max（TLS1.3 默认套件与默认分组完整保留）
 *   / TLS1.2 套件白名单仅 ECDHE+AEAD（无 CBC、无 DHE、无 RSA 密钥交换；
 *     该白名单只作用于 TLS≤1.2，TLS1.3 套件走独立 API、此处不限制）
 *   / ALPN 仅 http/1.1 / SNI + 主机名校验（IP 字面量走 IP 校验、不发 SNI）
 *   / CA 信任 = 内置 Mozilla 根证书包（cacert.h），不依赖设备 CA 路径。
 *
 * 可移植性：仅用 POSIX + OpenSSL 稳定 API（宿主 glibc 单测 / 设备 musl 同源码），
 * 不依赖 strcasestr 等 GNU 扩展。
 */
/* 特性面：_DEFAULT_SOURCE（glibc 与 musl 同口径：POSIX.1-2008 + inet_pton 等扩展；
 * 注意不能只定义 _POSIX_C_SOURCE——glibc 会因此关闭 MISC 面隐藏 inet_pton） */
#define _DEFAULT_SOURCE

#include "atls_http.h"

#include <arpa/inet.h> /* inet_pton（glibc 在此头；musl 亦提供） */
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#include <openssl/err.h>
#include <openssl/opensslv.h>
#include <openssl/ssl.h>
#include <openssl/x509v3.h>

#include "cacert.h"

/* ---------------- 常量 ---------------- */

#define ATLS_POLL_TICK_MS 200   /* 轮询片：取消响应粒度 */
#define ATLS_MAX_REDIRECTS 20   /* 与插件 httpx 跟跳上限一致 */
#define ATLS_MAX_RESPONSE (1u << 30) /* 响应体尺寸保护 1GiB */
#define ATLS_MAX_LINE 65536     /* 单行（状态行/头行/chunk 头）上限 */
#define ATLS_INIT_BODY_BUF (64 * 1024)
#define ATLS_HOST_BUF 512
#define ATLS_PATH_BUF 8192

/* TLS≤1.2 套件白名单：仅 ECDHE 密钥交换 + GCM/CHACHA20 AEAD（无 CBC/DHE/RSA kex）。
 * 注意：仅约束 TLS1.2 及以下；TLS1.3 套件不在此列（保持默认三套件）。
 * 域名连接必须带 SNI：目标服务端（:7113）无 default vhost，对无 SNI 握手回
 * alert internal error（80）——实测可复现，见 tls_handshake 的 SNI 设置注释。
 * 套件保持全量 AEAD 档。 */
#define ATLS_CIPHER_LIST "ECDHE+AESGCM:ECDHE+CHACHA20"

/* ---------------- 错误分类名 ---------------- */

const char *atls_kind_name(atls_err kind)
{
  switch (kind) {
  case ATLS_ERR_NONE:
    return "none";
  case ATLS_ERR_CONNECT_TIMEOUT:
    return "connect-timeout";
  case ATLS_ERR_READ_TIMEOUT:
    return "read-timeout";
  case ATLS_ERR_DNS:
    return "dns";
  case ATLS_ERR_REFUSED:
    return "refused";
  case ATLS_ERR_TLS_VERIFY:
    return "tls-verify";
  case ATLS_ERR_TLS:
    return "tls";
  case ATLS_ERR_IO:
    return "io";
  case ATLS_ERR_PROTOCOL:
    return "protocol";
  case ATLS_ERR_CANCELLED:
    return "cancelled";
  case ATLS_ERR_OOM:
    return "oom";
  case ATLS_ERR_BAD_URL:
    return "bad-url";
  }
  return "unknown";
}

/* ---------------- 基础类型 ---------------- */

typedef struct {
  volatile int *cancel;
  int timeout_ms; /* 每个阻塞读写操作的独立窗口（长轮询等待首字节亦计一次） */
} atls_wait_ctx;

/* 单连接 I/O 抽象（明文或 TLS 同接口；fd 恒为非阻塞）。
 * rbuf 读侧缓冲：行读/精确尺寸读不跨界，段内剩余字节留给下一次读，
 * 杜绝"一次 recv 的字节被行消费丢弃"这类丢字节缺陷。 */
typedef struct {
  int fd;
  SSL *ssl; /* NULL = 明文 */
  atls_wait_ctx wait;
  unsigned char rbuf[8192];
  size_t rbuf_off;
  size_t rbuf_len;
  int rbuf_eof;
} atls_conn;

/* 键值交错向量：items[2i]=key, items[2i+1]=value；count = 键值对数 */
typedef struct {
  char **items;
  size_t count; /* 键值对数 */
  size_t cap;   /* 项数容量（偶数） */
} kv_vec;

/* 纯值向量（Set-Cookie 用） */
typedef struct {
  char **items;
  size_t count;
  size_t cap;
} str_vec;

typedef struct {
  unsigned char *data;
  size_t len;
  size_t cap;
} buf;

/* ---------------- 小工具 ---------------- */

static void set_err(atls_response *out, atls_err kind, const char *fmt, ...)
    __attribute__((format(printf, 3, 4)));

static void set_err(atls_response *out, atls_err kind, const char *fmt, ...)
{
  va_list ap;
  out->err = kind;
  va_start(ap, fmt);
  vsnprintf(out->err_msg, sizeof(out->err_msg), fmt, ap);
  va_end(ap);
}

static void *xmalloc(size_t n)
{
  void *p = malloc(n ? n : 1);
  if (!p) {
    /* 小对象分配失败（行缓冲/头表）——进程内存已不可用，终止避免静默腐败 */
    abort();
  }
  return p;
}

static char *xstrdup(const char *s)
{
  size_t n = strlen(s) + 1;
  char *p = xmalloc(n);
  memcpy(p, s, n);
  return p;
}

static int64_t now_ms(void)
{
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* 轮询等待 fd 就绪：单片 ≤200ms。
 * 返回 0=就绪 / ATLS_ERR_CANCELLED / ATLS_ERR_READ_TIMEOUT / -errno */
static int poll_wait(int fd, int events, volatile int *cancel, int64_t deadline_ms)
{
  for (;;) {
    if (cancel && *cancel) {
      return ATLS_ERR_CANCELLED;
    }
    int left_ms = ATLS_POLL_TICK_MS;
    if (deadline_ms > 0) {
      int64_t remain = deadline_ms - now_ms();
      if (remain <= 0) {
        return ATLS_ERR_READ_TIMEOUT;
      }
      if (remain < ATLS_POLL_TICK_MS) {
        left_ms = (int)remain;
      }
    }
    struct pollfd pfd = {fd, (short)events, 0};
    int rc = poll(&pfd, 1, left_ms);
    if (rc < 0) {
      if (errno == EINTR) {
        continue;
      }
      return -errno;
    }
    if (rc == 0) {
      continue; /* 片超时：回循环查 deadline/cancel */
    }
    if (pfd.revents & (POLLERR | POLLNVAL)) {
      return 0; /* 交 read/write 判定 */
    }
    if (pfd.revents & (events == POLLIN ? POLLIN : POLLOUT)) {
      return 0;
    }
  }
}

/* ---------------- kv_vec / str_vec / buf ---------------- */

static void kv_push(kv_vec *v, char *key, char *value)
{
  if (v->count * 2 + 2 > v->cap) {
    v->cap = v->cap ? v->cap * 2 : 16;
    v->items = realloc(v->items, v->cap * sizeof(char *));
  }
  v->items[v->count * 2] = key;
  v->items[v->count * 2 + 1] = value;
  v->count++;
}

static void kv_free(kv_vec *v)
{
  for (size_t i = 0; i < v->count * 2; i++) {
    free(v->items[i]);
  }
  free(v->items);
  v->items = NULL;
  v->count = v->cap = 0;
}

static void str_push(str_vec *v, char *s)
{
  if (v->count + 1 > v->cap) {
    v->cap = v->cap ? v->cap * 2 : 4;
    v->items = realloc(v->items, v->cap * sizeof(char *));
  }
  v->items[v->count++] = s;
}

static void str_free(str_vec *v)
{
  for (size_t i = 0; i < v->count; i++) {
    free(v->items[i]);
  }
  free(v->items);
  v->items = NULL;
  v->count = v->cap = 0;
}

static int buf_append(buf *b, const unsigned char *data, size_t n)
{
  if (n > ATLS_MAX_RESPONSE - b->len) {
    return -1;
  }
  if (n > b->cap - b->len) {
    size_t nc = b->cap ? b->cap : ATLS_INIT_BODY_BUF;
    while (nc < b->len + n) {
      nc *= 2;
    }
    unsigned char *nd = realloc(b->data, nc);
    if (!nd) {
      return -1;
    }
    b->data = nd;
    b->cap = nc;
  }
  memcpy(b->data + b->len, data, n);
  b->len += n;
  return 0;
}

/* ---------------- URL 解析 ---------------- */

typedef struct {
  int is_tls;
  char host[ATLS_HOST_BUF];
  int port;
  char path[ATLS_PATH_BUF]; /* 含 query；空 = "/" */
} atls_url;

static int host_is_ip(const char *host)
{
  struct in_addr a4;
  struct in6_addr a6;
  if (inet_pton(AF_INET, host, &a4) == 1) {
    return 1;
  }
  return inet_pton(AF_INET6, host, &a6) == 1;
}

/* 解析 scheme://host[:port]/path[?query]；仅 http/https。0 成功 */
static int parse_url(const char *url, atls_url *out)
{
  memset(out, 0, sizeof(*out));
  const char *p = url;
  const char *rest;
  if (strncmp(p, "https://", 8) == 0) {
    out->is_tls = 1;
    out->port = 443;
    rest = p + 8;
  } else if (strncmp(p, "http://", 7) == 0) {
    out->is_tls = 0;
    out->port = 80;
    rest = p + 7;
  } else {
    return -1;
  }
  const char *slash = strchr(rest, '/');
  size_t hostlen = slash ? (size_t)(slash - rest) : strlen(rest);
  if (hostlen == 0 || hostlen >= ATLS_HOST_BUF) {
    return -1;
  }
  char hostbuf[ATLS_HOST_BUF];
  memcpy(hostbuf, rest, hostlen);
  hostbuf[hostlen] = 0;

  if (hostbuf[0] == '[') { /* [IPv6][:port] */
    const char *close = strchr(hostbuf, ']');
    if (!close) {
      return -1;
    }
    size_t hl = (size_t)(close - hostbuf - 1);
    memcpy(out->host, hostbuf + 1, hl);
    out->host[hl] = 0;
    if (close[1] == ':') {
      out->port = atoi(close + 2);
    }
  } else {
    const char *colon = strrchr(hostbuf, ':');
    if (colon && colon != hostbuf) {
      size_t hl = (size_t)(colon - hostbuf);
      memcpy(out->host, hostbuf, hl);
      out->host[hl] = 0;
      out->port = atoi(colon + 1);
    } else {
      snprintf(out->host, ATLS_HOST_BUF, "%s", hostbuf);
    }
  }
  if (out->port <= 0 || out->port > 65535) {
    return -1;
  }
  if (slash) {
    snprintf(out->path, ATLS_PATH_BUF, "%s", slash);
  } else {
    out->path[0] = '/';
    out->path[1] = 0;
  }
  return 0;
}

/* Location 三形：绝对 URL 直用 / //host/path 继承 scheme / /path 补当前 origin。
 * 返回 malloc 字符串或 NULL（非法相对位置） */
static char *resolve_location(const char *loc, const atls_url *base)
{
  if (loc && (strncmp(loc, "http://", 7) == 0 || strncmp(loc, "https://", 8) == 0)) {
    return xstrdup(loc);
  }
  char full[ATLS_HOST_BUF + ATLS_PATH_BUF + 16];
  const char *scheme = base->is_tls ? "https://" : "http://";
  if (loc && strncmp(loc, "//", 2) == 0) {
    snprintf(full, sizeof(full), "%s%s", scheme, loc);
  } else if (loc && loc[0] == '/') {
    char authority[ATLS_HOST_BUF + 8];
    if (base->port == (base->is_tls ? 443 : 80)) {
      snprintf(authority, sizeof(authority), "%s", base->host);
    } else {
      snprintf(authority, sizeof(authority), "%s:%d", base->host, base->port);
    }
    snprintf(full, sizeof(full), "%s%s%s", scheme, authority, loc);
  } else {
    return NULL;
  }
  return xstrdup(full);
}

/* ---------------- TCP 连接（非阻塞 + poll；遍历解析结果） ---------------- */

static int tcp_connect(const char *host, int port, int timeout_ms, volatile int *cancel,
                       atls_response *out)
{
  char portbuf[16];
  snprintf(portbuf, sizeof(portbuf), "%d", port);
  struct addrinfo hints;
  memset(&hints, 0, sizeof(hints));
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  struct addrinfo *res = NULL;
  int gai = getaddrinfo(host, portbuf, &hints, &res);
  if (gai != 0) {
    set_err(out, ATLS_ERR_DNS, "getaddrinfo failed for %s: %s", host, gai_strerror(gai));
    return -1;
  }
  int fd = -1;
  int last_errno = 0;
  int saw_refused = 0;
  int64_t deadline = now_ms() + timeout_ms;
  for (struct addrinfo *ai = res; ai && fd < 0; ai = ai->ai_next) {
    if (ai->ai_family != AF_INET && ai->ai_family != AF_INET6) {
      continue;
    }
    fd = socket(ai->ai_family, ai->ai_socktype | SOCK_NONBLOCK, ai->ai_protocol);
    if (fd < 0) {
      last_errno = errno;
      continue;
    }
    int rc = connect(fd, ai->ai_addr, ai->ai_addrlen);
    if (rc == 0) {
      break;
    }
    if (errno != EINPROGRESS) {
      if (errno == ECONNREFUSED) {
        saw_refused = 1;
      }
      last_errno = errno;
      close(fd);
      fd = -1;
      continue;
    }
    int prc = poll_wait(fd, POLLOUT, cancel, deadline);
    if (prc == ATLS_ERR_CANCELLED) {
      set_err(out, ATLS_ERR_CANCELLED, "request cancelled");
      close(fd);
      freeaddrinfo(res);
      return -1;
    }
    if (prc == ATLS_ERR_READ_TIMEOUT) {
      /* 建连窗耗尽（SYN 被黑洞）：记超时，试下一解析结果 */
      last_errno = ETIMEDOUT;
      close(fd);
      fd = -1;
      continue;
    }
    if (prc < 0) {
      last_errno = -prc;
      close(fd);
      fd = -1;
      continue;
    }
    int soerr = 0;
    socklen_t sl = sizeof(soerr);
    if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &soerr, &sl) < 0 || soerr != 0) {
      if (soerr == ECONNREFUSED) {
        saw_refused = 1;
      }
      last_errno = soerr ? soerr : errno;
      close(fd);
      fd = -1;
      continue;
    }
    break;
  }
  freeaddrinfo(res);
  if (fd < 0) {
    if (saw_refused) {
      set_err(out, ATLS_ERR_REFUSED, "connection refused to %s:%d", host, port);
    } else if (last_errno == ETIMEDOUT) {
      set_err(out, ATLS_ERR_CONNECT_TIMEOUT, "connect timeout to %s:%d", host, port);
    } else if (last_errno == EHOSTUNREACH || last_errno == ENETUNREACH) {
      set_err(out, ATLS_ERR_REFUSED, "network unreachable to %s:%d", host, port);
    } else {
      set_err(out, ATLS_ERR_CONNECT_TIMEOUT, "connect to %s:%d failed within %d ms: %s", host,
              port, timeout_ms, strerror(last_errno ? last_errno : ETIMEDOUT));
    }
    return -1;
  }
  int flag = 1;
  setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));
  return fd; /* 保持非阻塞：SSL WANT_x 复用同一 poll 纪律 */
}

/* ---------------- TLS 握手 ---------------- */

static SSL_CTX *make_tls_ctx(atls_response *out)
{
  SSL_CTX *ctx = SSL_CTX_new(TLS_client_method());
  if (!ctx) {
    set_err(out, ATLS_ERR_TLS, "ssl ctx create failed");
    return NULL;
  }
  /* min=TLS1.2，不设 max：TLS1.3 默认套件与默认分组完整保留 */
  SSL_CTX_set_min_proto_version(ctx, TLS1_2_VERSION);
  /* 白名单只作用于 TLS≤1.2（TLS1.3 套件走 SSL_CTX_set_ciphersuites，此处不动） */
  if (SSL_CTX_set_cipher_list(ctx, ATLS_CIPHER_LIST) != 1) {
    set_err(out, ATLS_ERR_TLS, "cipher list apply failed");
    goto fail;
  }
  /* ALPN 仅 http/1.1（绝不 h2）：长度前缀编码 */
  static const unsigned char alpn[] = {8, 'h', 't', 't', 'p', '/', '1', '.', '1'};
  if (SSL_CTX_set_alpn_protos(ctx, alpn, sizeof(alpn)) != 0) {
    set_err(out, ATLS_ERR_TLS, "alpn apply failed");
    goto fail;
  }
  /* 内置 Mozilla 根证书包（不依赖设备 CA 路径） */
  X509_STORE *store = SSL_CTX_get_cert_store(ctx);
  BIO *bio = BIO_new_mem_buf(ATLS_CACERT_PEM, (int)ATLS_CACERT_PEM_LEN);
  if (!bio) {
    set_err(out, ATLS_ERR_TLS, "ca bundle bio failed");
    goto fail;
  }
  int loaded = 0;
  X509 *cert;
  while ((cert = PEM_read_bio_X509(bio, NULL, NULL, NULL)) != NULL) {
    if (X509_STORE_add_cert(store, cert) == 1) {
      loaded++;
    }
    X509_free(cert);
  }
  BIO_free(bio);
  ERR_clear_error(); /* 收尾的 "no start line" 属正常 */
  if (loaded < 50) {
    set_err(out, ATLS_ERR_TLS, "ca bundle load incomplete (%d certs)", loaded);
    goto fail;
  }
  SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER, NULL);
  SSL_CTX_set_session_cache_mode(ctx, SSL_SESS_CACHE_OFF); /* 无 resumption，最简指纹 */
  return ctx;
fail:
  SSL_CTX_free(ctx);
  return NULL;
}

/* 非阻塞 TLS 握手；deadline 属"建连"语义（建连超时窗）。0 成功 */
static int tls_handshake(atls_conn *c, const char *host, int64_t deadline, atls_response *out)
{
  SSL_CTX *ctx = make_tls_ctx(out);
  if (!ctx) {
    return -1;
  }
  SSL *ssl = SSL_new(ctx);
  if (!ssl) {
    SSL_CTX_free(ctx);
    set_err(out, ATLS_ERR_TLS, "ssl new failed");
    return -1;
  }
  /* BIO_NOCLOSE：SSL 持有 BIO 但不持有 fd，fd 仍由 conn_close 统一关闭
   *（与旧 SSL_set_fd 的属主语义一致；SSL_set_fd 在 3.x 属弃用 API，
   * 缩减构建 no-deprecated 下不再提供） */
  BIO *fbio = BIO_new_fd(c->fd, BIO_NOCLOSE);
  if (!fbio) {
    set_err(out, ATLS_ERR_TLS, "ssl bio new failed");
    goto fail;
  }
  SSL_set_bio(ssl, fbio, fbio); /* 3.x 起返回 void，BIO 属主移交 SSL */
  /* 证书校验 + SNI。注意：OpenSSL 3.x 的 SSL_set1_host 只写校验参数，**不发 SNI**
   *（SNI 由 SSL_set_tlsext_host_name 独占，见 tls_construct_ctos_server_name 只读
   * s->ext.hostname）。域名连接必须显式发 SNI，否则：
   *  1) 目标服务端无 default vhost，对无 SNI 握手直接回 alert internal error（80）；
   *  2) 链路 DPI 按「SNI 属被拦域族 × 客户端指纹」拦，无 SNI 时规则不触发
   *     但服务端必拒——两种情况域名连接都到不了 HTTP 层。
   * IP 字面量走 IP 校验且不发 SNI（RFC 6066）。 */
  if (host_is_ip(host)) {
    X509_VERIFY_PARAM *vp = SSL_get0_param(ssl);
    if (!vp || X509_VERIFY_PARAM_set1_ip_asc(vp, host) != 1) {
      set_err(out, ATLS_ERR_TLS, "ip verify param set failed for %s", host);
      goto fail;
    }
  } else {
    if (SSL_set1_host(ssl, host) != 1 || SSL_set_tlsext_host_name(ssl, host) != 1) {
      set_err(out, ATLS_ERR_TLS, "sni/host set failed for %s", host);
      goto fail;
    }
  }
  for (;;) {
    int rc = SSL_connect(ssl);
    if (rc == 1) {
      break;
    }
    int err = SSL_get_error(ssl, rc);
    if (err == SSL_ERROR_WANT_READ || err == SSL_ERROR_WANT_WRITE) {
      int prc = poll_wait(c->fd, err == SSL_ERROR_WANT_READ ? POLLIN : POLLOUT, c->wait.cancel,
                          deadline);
      if (prc == ATLS_ERR_CANCELLED) {
        set_err(out, ATLS_ERR_CANCELLED, "request cancelled");
        goto fail;
      }
      if (prc < 0) {
        set_err(out, ATLS_ERR_TLS, "handshake i/o error: %s", strerror(-prc));
        goto fail;
      }
      continue;
    }
    if (err == SSL_ERROR_SYSCALL) {
      /* 握手阶段 RST/EOF——链路中间设备按 ClientHello 指纹拦截的典型形态 */
      set_err(out, ATLS_ERR_TLS, "ssl connection reset during handshake (errno=%d %s)", errno,
              strerror(errno));
      goto fail;
    }
    int vcode = SSL_get_verify_result(ssl);
    if (vcode != X509_V_OK) {
      set_err(out, ATLS_ERR_TLS_VERIFY, "certificate verify failed: %s",
              X509_verify_cert_error_string(vcode));
      goto fail;
    }
    char ebuf[256] = {0};
    unsigned long e = ERR_get_error();
    if (e != 0) {
      ERR_error_string_n(e, ebuf, sizeof(ebuf));
    }
    set_err(out, ATLS_ERR_TLS, "ssl handshake failed: %s", ebuf[0] ? ebuf : "unknown");
    goto fail;
  }
  c->ssl = ssl;
  SSL_CTX_free(ctx);
  return 0;
fail:
  SSL_free(ssl);
  SSL_CTX_free(ctx);
  return -1;
}

/* ---------------- 连接 I/O ---------------- */

/* 统一读入口（缓冲流）：至多取 tmp_cap 字节（*got>0），多出的留在 rbuf 交下次读。
 * 0 = 有数据 / 1 = 对端关闭（*got 可能为 0）/ -1 = 错误（resp->err 已置）。
 * 每次调用一个独立读窗口（wait.timeout_ms）——等待首字节与中途断续都受窗约束。 */
static int conn_stream(atls_conn *c, unsigned char *tmp, size_t tmp_cap, size_t *got,
                       atls_response *resp)
{
  *got = 0;
  if (c->rbuf_off < c->rbuf_len) {
    size_t take = c->rbuf_len - c->rbuf_off;
    if (take > tmp_cap) {
      take = tmp_cap;
    }
    memcpy(tmp, c->rbuf + c->rbuf_off, take);
    c->rbuf_off += take;
    *got = take;
    return 0;
  }
  if (c->rbuf_eof) {
    return 1;
  }
  int64_t deadline = c->wait.timeout_ms > 0 ? now_ms() + c->wait.timeout_ms : 0;
  for (;;) {
    int n = 0;
    if (c->ssl) {
      n = SSL_read(c->ssl, c->rbuf, (int)sizeof(c->rbuf));
      if (n <= 0) {
        int err = SSL_get_error(c->ssl, n);
        if (err == SSL_ERROR_WANT_READ || err == SSL_ERROR_WANT_WRITE) {
          int prc = poll_wait(c->fd, POLLIN, c->wait.cancel, deadline);
          if (prc == ATLS_ERR_CANCELLED) {
            set_err(resp, ATLS_ERR_CANCELLED, "request cancelled");
            return -1;
          }
          if (prc == ATLS_ERR_READ_TIMEOUT) {
            set_err(resp, ATLS_ERR_READ_TIMEOUT, "read timeout");
            return -1;
          }
          if (prc < 0) {
            set_err(resp, ATLS_ERR_IO, "poll for read failed: %s", strerror(-prc));
            return -1;
          }
          continue;
        }
        if (err == SSL_ERROR_ZERO_RETURN) {
          c->rbuf_eof = 1;
          return 1; /* 对端有序关闭 */
        }
        set_err(resp, ATLS_ERR_IO, "tls read failed");
        return -1; /* SYSCALL(RST/EOF) 或协议错误 */
      }
    } else {
      ssize_t rc = recv(c->fd, c->rbuf, sizeof(c->rbuf), 0);
      if (rc < 0) {
        if (errno == EINTR) {
          continue;
        }
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
          int prc = poll_wait(c->fd, POLLIN, c->wait.cancel, deadline);
          if (prc == ATLS_ERR_CANCELLED) {
            set_err(resp, ATLS_ERR_CANCELLED, "request cancelled");
            return -1;
          }
          if (prc == ATLS_ERR_READ_TIMEOUT) {
            set_err(resp, ATLS_ERR_READ_TIMEOUT, "read timeout");
            return -1;
          }
          if (prc < 0) {
            set_err(resp, ATLS_ERR_IO, "poll for read failed: %s", strerror(-prc));
            return -1;
          }
          continue;
        }
        set_err(resp, ATLS_ERR_IO, "read failed: %s", strerror(errno));
        return -1;
      }
      if (rc == 0) {
        c->rbuf_eof = 1;
        return 1;
      }
      n = (int)rc;
    }
    c->rbuf_off = 0;
    c->rbuf_len = (size_t)n;
    size_t take = (size_t)n > tmp_cap ? tmp_cap : (size_t)n;
    memcpy(tmp, c->rbuf, take);
    c->rbuf_off = take;
    *got = take;
    return 0;
  }
}

static void conn_close(atls_conn *c)
{
  if (c->ssl) {
    SSL_shutdown(c->ssl); /* best-effort（Connection: close 口径，不强求挥手完成） */
    SSL_free(c->ssl);
    c->ssl = NULL;
  }
  if (c->fd >= 0) {
    close(c->fd);
    c->fd = -1;
  }
}

/* 写完整块（超时/取消纪律同读）。0 成功 */
static int conn_write_all(atls_conn *c, const unsigned char *data, size_t len, atls_response *out)
{
  size_t off = 0;
  int64_t deadline = c->wait.timeout_ms > 0 ? now_ms() + c->wait.timeout_ms : 0;
  while (off < len) {
    if (c->ssl) {
      int rc = SSL_write(c->ssl, data + off, (int)(len - off));
      if (rc <= 0) {
        int err = SSL_get_error(c->ssl, rc);
        if (err == SSL_ERROR_WANT_WRITE || err == SSL_ERROR_WANT_READ) {
          int prc = poll_wait(c->fd, POLLOUT, c->wait.cancel, deadline);
          if (prc == ATLS_ERR_CANCELLED) {
            set_err(out, ATLS_ERR_CANCELLED, "request cancelled");
            return -1;
          }
          if (prc == ATLS_ERR_READ_TIMEOUT) {
            set_err(out, ATLS_ERR_READ_TIMEOUT, "write timeout");
            return -1;
          }
          if (prc < 0) {
            set_err(out, ATLS_ERR_IO, "write failed: %s", strerror(-prc));
            return -1;
          }
          continue;
        }
        set_err(out, ATLS_ERR_IO, "tls write failed");
        return -1;
      }
      off += (size_t)rc;
      continue;
    }
    ssize_t r2 = send(c->fd, data + off, len - off, MSG_NOSIGNAL);
    if (r2 >= 0) {
      off += (size_t)r2;
      continue;
    }
    if (errno == EINTR) {
      continue;
    }
    if (errno == EAGAIN || errno == EWOULDBLOCK) {
      int prc = poll_wait(c->fd, POLLOUT, c->wait.cancel, deadline);
      if (prc == ATLS_ERR_CANCELLED) {
        set_err(out, ATLS_ERR_CANCELLED, "request cancelled");
        return -1;
      }
      if (prc == ATLS_ERR_READ_TIMEOUT) {
        set_err(out, ATLS_ERR_READ_TIMEOUT, "write timeout");
        return -1;
      }
      if (prc < 0) {
        set_err(out, ATLS_ERR_IO, "write failed: %s", strerror(-prc));
        return -1;
      }
      continue;
    }
    set_err(out, ATLS_ERR_IO, "write failed: %s", strerror(errno));
    return -1;
  }
  return 0;
}

/* 读一行（行内容含行尾 CRLF，消费端自行容忍/裁剪；EOF 时的半行允许返回交上层判格式）。
 * 0 成功（*out=malloc 行）/ -1 错误（resp->err 已置）。走缓冲流：段内余字节不丢。 */
static int read_line(atls_conn *c, char **out, atls_response *resp)
{
  const size_t line_cap = ATLS_MAX_LINE + 2;
  char *line = xmalloc(line_cap);
  size_t n = 0;
  for (;;) {
    unsigned char ch = 0;
    size_t got = 0;
    int rc = conn_stream(c, &ch, 1, &got, resp);
    if (rc == 1) {
      if (n > 0) {
        line[n] = 0; /* 无行尾收尾（异常响应），交上层判 */
        *out = line;
        return 0;
      }
      set_err(resp, ATLS_ERR_IO, "connection closed before response (EOF)");
      free(line);
      return ATLS_ERR_IO;
    }
    if (rc != 0) {
      free(line);
      return -1; /* resp->err 已由 conn_stream 置好 */
    }
    if (n + 1 >= line_cap) {
      free(line);
      set_err(resp, ATLS_ERR_PROTOCOL, "response line too long");
      return ATLS_ERR_PROTOCOL;
    }
    line[n++] = (char)ch;
    if (ch == '\n') {
      line[n] = 0;
      *out = line;
      return 0;
    }
  }
}

/* ---------------- 响应解析 ---------------- */

static int header_str_eq(const char *a, const char *b)
{
  while (*a && *b) {
    if ((unsigned char)(*a | 0x20) != (unsigned char)(*b | 0x20)) {
      return 0;
    }
    a++;
    b++;
  }
  return *a == 0 && *b == 0;
}

static int header_contains_ci(const char *hay, const char *needle)
{
  size_t nl = strlen(needle);
  size_t hl = strlen(hay);
  if (nl == 0 || nl > hl) {
    return 0;
  }
  for (size_t i = 0; i + nl <= hl; i++) {
    int ok = 1;
    for (size_t j = 0; j < nl; j++) {
      if ((unsigned char)(hay[i + j] | 0x20) != (unsigned char)(needle[j] | 0x20)) {
        ok = 0;
        break;
      }
    }
    if (ok) {
      return 1;
    }
  }
  return 0;
}

static int find_header(char **items, size_t pair_count, const char *name, const char **val)
{
  for (size_t i = 0; i < pair_count; i++) {
    if (header_str_eq(items[i * 2], name)) {
      *val = items[i * 2 + 1];
      return 1;
    }
  }
  return 0;
}

/* 读一个完整响应头段（状态行 + 头表，Set-Cookie 分桶）。0 成功 */
static int read_response_head(atls_conn *c, int *status, kv_vec *headers, str_vec *set_cookies,
                              atls_response *resp)
{
  char *line = NULL;
  if (read_line(c, &line, resp) != 0) {
    return -1; /* resp->err 已置（含超时/取消/IO 具体分类） */
  }
  /* 状态行 "HTTP/1.x DDD ..."：[8]=' '，[9..11] 三位数字，[12] ' ' 或行尾 */
  if (strncmp(line, "HTTP/1.", 7) != 0 || line[8] != ' ' || line[9] < '0' || line[9] > '9' ||
      line[10] < '0' || line[10] > '9' || line[11] < '0' || line[11] > '9' ||
      (line[12] != 0 && line[12] != ' ')) {
    char snippet[64];
    snprintf(snippet, sizeof(snippet), "%.60s", line);
    free(line);
    set_err(resp, ATLS_ERR_PROTOCOL, "malformed status line: %s", snippet);
    return -1;
  }
  int st = (line[9] - '0') * 100 + (line[10] - '0') * 10 + (line[11] - '0');
  *status = st;
  free(line);

  for (;;) {
    if (read_line(c, &line, resp) != 0) {
      return -1; /* resp->err 已置 */
    }
    if (line[0] == '\r' || line[0] == '\n' || line[0] == 0) {
      free(line);
      return 0; /* 头段结束 */
    }
    char *colon = strchr(line, ':');
    if (!colon) {
      char snippet[64];
      snprintf(snippet, sizeof(snippet), "%.60s", line);
      free(line);
      set_err(resp, ATLS_ERR_PROTOCOL, "malformed header line: %s", snippet);
      return -1;
    }
    *colon = 0;
    char *key = line;
    char *val = colon + 1;
    size_t klen = (size_t)(colon - line);
    while (klen > 0 && (key[klen - 1] == ' ' || key[klen - 1] == '\t')) {
      key[--klen] = 0;
    }
    while (*val == ' ' || *val == '\t') {
      val++;
    }
    size_t vlen = strlen(val);
    while (vlen > 0 && (val[vlen - 1] == '\r' || val[vlen - 1] == '\n' || val[vlen - 1] == ' ' ||
                        val[vlen - 1] == '\t')) {
      val[--vlen] = 0;
    }
    char *key_lower = xmalloc(klen + 1);
    for (size_t i = 0; i < klen; i++) {
      key_lower[i] = (char)((unsigned char)key[i] | 0x20);
    }
    key_lower[klen] = 0;
    if (header_str_eq(key_lower, "set-cookie")) {
      str_push(set_cookies, xstrdup(val));
    } else {
      kv_push(headers, key_lower, xstrdup(val));
    }
    free(line);
  }
}

/* chunked 体：size 行（hex，';' 后扩展忽略）→ size 字节 + CRLF，循环至 0 块 → trailer 至空行 */
static int read_body_chunked(atls_conn *c, buf *body, atls_response *resp)
{
  for (;;) {
    char *line = NULL;
    if (read_line(c, &line, resp) != 0) {
      return -1;
    }
    char *semi = strchr(line, ';');
    if (semi) {
      *semi = 0;
    }
    char *endp = NULL;
    unsigned long size = strtoul(line, &endp, 16);
    int bad_size = (endp == line) || (size == 0 && line[0] != '0');
    char snippet[64];
    snprintf(snippet, sizeof(snippet), "%.60s", line);
    free(line);
    if (bad_size) {
      set_err(resp, ATLS_ERR_PROTOCOL, "malformed chunk size: %s", snippet);
      return ATLS_ERR_PROTOCOL;
    }
    if (size == 0) {
      /* trailer 头：读至空行（忽略内容） */
      for (;;) {
        char *t = NULL;
        if (read_line(c, &t, resp) != 0) {
          return -1;
        }
        if (t[0] == '\r' || t[0] == '\n' || t[0] == 0) {
          free(t);
          return 0;
        }
        free(t);
      }
    }
    unsigned long remain = size;
    while (remain > 0) {
      unsigned char tmp[8192];
      size_t want = sizeof(tmp);
      if (want > remain) {
        want = (size_t)remain;
      }
      size_t got = 0;
      int rc = conn_stream(c, tmp, want, &got, resp);
      if (rc == 1) {
        set_err(resp, ATLS_ERR_IO, "connection closed before full response body (EOF)");
        return ATLS_ERR_IO;
      }
      if (rc != 0) {
        return -1; /* resp->err 已置 */
      }
      if (buf_append(body, tmp, got) != 0) {
        set_err(resp, ATLS_ERR_OOM, "response body too large");
        return ATLS_ERR_OOM;
      }
      remain -= (unsigned long)got;
    }
    /* 块后 CRLF（缓冲流精确取 2 字节，余量留给下一块 size 行） */
    char crlf[2] = {0, 0};
    size_t have = 0;
    while (have < 2) {
      size_t got = 0;
      int rc = conn_stream(c, (unsigned char *)(crlf + have), 2 - have, &got, resp);
      if (rc == 1) {
        set_err(resp, ATLS_ERR_IO, "connection closed before full response body (EOF)");
        return ATLS_ERR_IO;
      }
      if (rc != 0) {
        return -1; /* resp->err 已置 */
      }
      have += got;
    }
    if (crlf[0] != '\r' || crlf[1] != '\n') {
      set_err(resp, ATLS_ERR_PROTOCOL, "missing CRLF after chunk");
      return ATLS_ERR_PROTOCOL;
    }
  }
}

/* 按 Content-Length / chunked / 至关闭 读体。HEAD/204/304/1xx 无体。0 成功 */
static int read_response_body(atls_conn *c, char **hdr_items, size_t hdr_pairs, int status,
                              int method_head, buf *body, atls_response *resp)
{
  if (method_head || status == 204 || status == 304 || (status >= 100 && status < 200)) {
    return 0;
  }
  const char *te = NULL;
  const char *cl = NULL;
  for (size_t i = 0; i < hdr_pairs; i++) {
    if (header_str_eq(hdr_items[i * 2], "transfer-encoding")) {
      te = hdr_items[i * 2 + 1];
    } else if (header_str_eq(hdr_items[i * 2], "content-length")) {
      cl = hdr_items[i * 2 + 1];
    }
  }
  if (te && header_contains_ci(te, "chunked")) {
    return read_body_chunked(c, body, resp);
  }
  if (cl) {
    unsigned long remain = strtoul(cl, NULL, 10);
    while (remain > 0) {
      unsigned char tmp[8192];
      size_t want = sizeof(tmp);
      if (want > remain) {
        want = (size_t)remain;
      }
      size_t got = 0;
      int rc = conn_stream(c, tmp, want, &got, resp);
      if (rc == 1) {
        set_err(resp, ATLS_ERR_IO, "connection closed before full response body (EOF)");
        return ATLS_ERR_IO;
      }
      if (rc != 0) {
        return -1; /* resp->err 已置 */
      }
      if (buf_append(body, tmp, got) != 0) {
        set_err(resp, ATLS_ERR_OOM, "response body too large");
        return ATLS_ERR_OOM;
      }
      remain -= (unsigned long)got;
    }
    return 0;
  }
  /* 无长度：读至对端关闭（我们发 Connection: close，服务端关连接即收尾） */
  for (;;) {
    unsigned char tmp[8192];
    size_t got = 0;
    int rc = conn_stream(c, tmp, sizeof(tmp), &got, resp);
    if (got > 0 && buf_append(body, tmp, got) != 0) {
      set_err(resp, ATLS_ERR_OOM, "response body too large");
      return ATLS_ERR_OOM;
    }
    if (rc == 1) {
      return 0; /* 干净关闭 */
    }
    if (rc != 0) {
      return -1; /* resp->err 已置 */
    }
  }
}

/* 请求头缓冲追加（溢出即判负并置 *off=-1，杜绝负 size 进 snprintf 的 UB） */
static int head_append(char *buf, size_t cap, int *off, const char *fmt, ...)
{
  if (*off < 0 || (size_t)*off >= cap) {
    *off = -1;
    return -1;
  }
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(buf + *off, cap - (size_t)*off, fmt, ap);
  va_end(ap);
  if (n < 0 || (size_t)n >= cap - (size_t)*off) {
    *off = -1;
    return -1;
  }
  *off += n;
  return 0;
}

/* ---------------- 请求线+头+体的构造与发送（整响应/流式单跳共用前半） ----------------
 * 0 = 请求完整发出；-1 = 头溢出或写失败（*out 置错误，连接由调用方关闭）。 */
static int build_and_send_request(atls_conn *conn, const atls_url *u, const char *method,
                                  const atls_request_opts *opts, const unsigned char *body,
                                  size_t body_len, int drop_auth, atls_response *out)
{
  atls_response local;
  memset(&local, 0, sizeof(local));
  /* 请求线 + 头（溢出即判负） */
  char req_head[ATLS_PATH_BUF + ATLS_HOST_BUF + 4096];
  int off = 0;
  if (head_append(req_head, sizeof(req_head), &off, "%s %s HTTP/1.1\r\n", method, u->path) != 0) {
    goto head_overflow;
  }
  int host_set = 0;
  for (size_t i = 0; i < opts->header_count; i++) {
    if (header_str_eq(opts->header_keys[i], "host")) {
      host_set = 1;
      break;
    }
  }
  if (!host_set) {
    if (u->port == (u->is_tls ? 443 : 80)) {
      if (head_append(req_head, sizeof(req_head), &off, "Host: %s\r\n", u->host) != 0) {
        goto head_overflow;
      }
    } else {
      if (head_append(req_head, sizeof(req_head), &off, "Host: %s:%d\r\n", u->host, u->port) !=
          0) {
        goto head_overflow;
      }
    }
  }
  for (size_t i = 0; i < opts->header_count; i++) {
    const char *k = opts->header_keys[i];
    if (header_str_eq(k, "connection") || header_str_eq(k, "content-length")) {
      continue; /* 由本层统一注入 */
    }
    if (drop_auth && (header_str_eq(k, "authorization") || header_str_eq(k, "cookie"))) {
      continue; /* 跟跳跨主机：凭据不跨源 */
    }
    if (head_append(req_head, sizeof(req_head), &off, "%s: %s\r\n", k, opts->header_values[i]) !=
        0) {
      goto head_overflow;
    }
  }
  int has_body = body_len > 0 || strcmp(method, "POST") == 0 || strcmp(method, "PUT") == 0 ||
                 strcmp(method, "PATCH") == 0;
  if (has_body &&
      head_append(req_head, sizeof(req_head), &off, "Content-Length: %zu\r\n", body_len) != 0) {
    goto head_overflow;
  }
  if (head_append(req_head, sizeof(req_head), &off, "Connection: close\r\n\r\n") != 0) {
    goto head_overflow;
  }
  goto head_done;
head_overflow:
  set_err(&local, ATLS_ERR_PROTOCOL, "request headers overflow");
head_done:
  if (off < 0) {
    *out = local;
    return -1;
  }
  if (conn_write_all(conn, (const unsigned char *)req_head, (size_t)off, &local) != 0) {
    *out = local;
    return -1;
  }
  if (body_len > 0) {
    if (conn_write_all(conn, body, body_len, &local) != 0) {
      *out = local;
      return -1;
    }
  }
  return 0;
}

/* ---------------- 单跳执行（建连→请求→完整响应） ---------------- */

static int do_one_hop(const atls_url *u, const char *method, const atls_request_opts *opts,
                      const unsigned char *body, size_t body_len, int drop_auth,
                      atls_response *out)
{
  atls_response local;
  memset(&local, 0, sizeof(local));
  kv_vec headers = {0};
  str_vec set_cookies = {0};

  int fd = tcp_connect(u->host, u->port, opts->connect_timeout_ms, opts->cancel, &local);
  if (fd < 0) {
    *out = local;
    return -1;
  }
  atls_conn conn;
  memset(&conn, 0, sizeof(conn));
  conn.fd = fd;
  conn.ssl = NULL;
  conn.wait.cancel = opts->cancel;
  conn.wait.timeout_ms = opts->connect_timeout_ms; /* 写阶段（请求头/体）用建连窗 */
  if (u->is_tls) {
    int64_t deadline = now_ms() + opts->connect_timeout_ms;
    if (tls_handshake(&conn, u->host, deadline, &local) != 0) {
      conn_close(&conn);
      *out = local;
      return -1;
    }
  }

  if (build_and_send_request(&conn, u, method, opts, body, body_len, drop_auth, &local) != 0) {
    conn_close(&conn);
    *out = local;
    return -1;
  }

  /* 读响应（每次读一个独立窗口 = read_timeout_ms；长轮询在此等数据或窗尽） */
  conn.wait.timeout_ms = opts->read_timeout_ms;
  int status = 0;
  if (read_response_head(&conn, &status, &headers, &set_cookies, &local) != 0) {
    *out = local;
    conn_close(&conn);
    kv_free(&headers);
    str_free(&set_cookies);
    return -1;
  }
  while (status == 100) { /* 100-continue：丢弃中间头，读最终响应 */
    kv_free(&headers);
    str_free(&set_cookies);
    if (read_response_head(&conn, &status, &headers, &set_cookies, &local) != 0) {
      *out = local;
      conn_close(&conn);
      kv_free(&headers);
      str_free(&set_cookies);
      return -1;
    }
  }
  buf bodybuf = {0};
  if (read_response_body(&conn, headers.items, headers.count, status,
                         strcmp(method, "HEAD") == 0, &bodybuf, &local) != 0) {
    *out = local;
    conn_close(&conn);
    kv_free(&headers);
    str_free(&set_cookies);
    free(bodybuf.data);
    return -1;
  }
  conn_close(&conn);

  local.status = status;
  local.body = bodybuf.data;
  local.body_len = bodybuf.len;
  local.headers = headers.items;
  local.header_count = headers.count; /* 键值对数；items[2i]/items[2i+1] */
  local.set_cookies = set_cookies.items;
  local.set_cookie_count = set_cookies.count;
  local.err = ATLS_ERR_NONE;
  *out = local;
  return 0;
}

/* ---------------- 入口 ---------------- */

int atls_request(const atls_request_opts *opts, atls_response *out)
{
  memset(out, 0, sizeof(*out));
  if (!opts || !opts->url || !opts->method || opts->url[0] == 0 || opts->method[0] == 0) {
    set_err(out, ATLS_ERR_BAD_URL, "missing url or method");
    return -1;
  }
  const char *cur_method = opts->method;
  const unsigned char *cur_body = opts->body;
  size_t cur_body_len = opts->body_len;
  char *current = xstrdup(opts->url);
  char original_host[ATLS_HOST_BUF] = {0};

  for (int hop = 0; hop <= ATLS_MAX_REDIRECTS; hop++) {
    atls_url u;
    if (parse_url(current, &u) != 0) {
      set_err(out, ATLS_ERR_BAD_URL, "bad url: %.160s", current);
      free(current);
      return -1;
    }
    if (hop == 0) {
      snprintf(original_host, sizeof(original_host), "%s", u.host);
    }
    int drop_auth = hop > 0 && strcasecmp(u.host, original_host) != 0;
    atls_response one;
    if (do_one_hop(&u, cur_method, opts, cur_body, cur_body_len, drop_auth, &one) != 0) {
      *out = one;
      free(current);
      return -1;
    }
    int is_redirect = one.status == 301 || one.status == 302 || one.status == 303 ||
                      one.status == 307 || one.status == 308;
    if (!is_redirect) {
      free(current);
      *out = one;
      return 0;
    }
    const char *loc = NULL;
    if (!find_header(one.headers, one.header_count, "location", &loc) || !loc || loc[0] == 0) {
      set_err(out, ATLS_ERR_PROTOCOL, "redirect %d without location", one.status);
      atls_response_free(&one);
      free(current);
      return -1;
    }
    char *next = resolve_location(loc, &u);
    if (!next) {
      set_err(out, ATLS_ERR_PROTOCOL, "unresolvable redirect location: %.160s", loc);
      atls_response_free(&one);
      free(current);
      return -1;
    }
    /* httpx 口径：303 恒转 GET 去体；301/302 对 POST 转 GET 去体；307/308 保持 */
    int to_get = one.status == 303 ||
                 ((one.status == 301 || one.status == 302) && strcmp(cur_method, "POST") == 0);
    atls_response_free(&one);
    free(current);
    current = next;
    if (to_get) {
      cur_method = "GET";
      cur_body = NULL;
      cur_body_len = 0;
    }
  }
  set_err(out, ATLS_ERR_PROTOCOL, "too many redirects (> %d)", ATLS_MAX_REDIRECTS);
  free(current);
  return -1;
}

/* ---------------- 流式响应（SSE 等：读头后按传输分块交付，不整包累积） ---------------- */

/* 推送一个数据块：尺寸保护 + on_data。0 继续；-1 中止/失败（resp->err 已置） */
static int stream_deliver(const atls_stream_cbs *cbs, const unsigned char *tmp, size_t got,
                          size_t *delivered, atls_response *resp)
{
  if (got == 0) {
    return 0;
  }
  *delivered += got;
  if (*delivered > ATLS_MAX_RESPONSE) {
    set_err(resp, ATLS_ERR_OOM, "response body too large");
    return -1;
  }
  if (cbs->on_data(cbs->ud, tmp, got) != 0) {
    set_err(resp, ATLS_ERR_CANCELLED, "aborted by stream consumer");
    return -1;
  }
  return 0;
}

/* 按 chunked / Content-Length / 至关闭 流式读体（read_response_body 的分块交付变体）。0 成功 */
static int read_body_stream(atls_conn *c, char **hdr_items, size_t hdr_pairs, int status,
                            int method_head, const atls_stream_cbs *cbs, atls_response *resp)
{
  if (method_head || status == 204 || status == 304 || (status >= 100 && status < 200)) {
    return 0;
  }
  const char *te = NULL;
  const char *cl = NULL;
  for (size_t i = 0; i < hdr_pairs; i++) {
    if (header_str_eq(hdr_items[i * 2], "transfer-encoding")) {
      te = hdr_items[i * 2 + 1];
    } else if (header_str_eq(hdr_items[i * 2], "content-length")) {
      cl = hdr_items[i * 2 + 1];
    }
  }
  size_t delivered = 0;
  if (te && header_contains_ci(te, "chunked")) {
    for (;;) {
      char *line = NULL;
      if (read_line(c, &line, resp) != 0) {
        return -1;
      }
      char *semi = strchr(line, ';');
      if (semi) {
        *semi = 0;
      }
      char *endp = NULL;
      unsigned long size = strtoul(line, &endp, 16);
      int bad_size = (endp == line) || (size == 0 && line[0] != '0');
      char snippet[64];
      snprintf(snippet, sizeof(snippet), "%.60s", line);
      free(line);
      if (bad_size) {
        set_err(resp, ATLS_ERR_PROTOCOL, "malformed chunk size: %s", snippet);
        return -1;
      }
      if (size == 0) {
        /* trailer 头：读至空行（忽略内容） */
        for (;;) {
          char *t = NULL;
          if (read_line(c, &t, resp) != 0) {
            return -1;
          }
          if (t[0] == '\r' || t[0] == '\n' || t[0] == 0) {
            free(t);
            return 0;
          }
          free(t);
        }
      }
      unsigned long remain = size;
      while (remain > 0) {
        unsigned char tmp[8192];
        size_t want = sizeof(tmp);
        if (want > remain) {
          want = (size_t)remain;
        }
        size_t got = 0;
        int rc = conn_stream(c, tmp, want, &got, resp);
        if (rc == 1) {
          set_err(resp, ATLS_ERR_IO, "connection closed before full response body (EOF)");
          return -1;
        }
        if (rc != 0) {
          return -1; /* resp->err 已置 */
        }
        if (stream_deliver(cbs, tmp, got, &delivered, resp) != 0) {
          return -1;
        }
        remain -= (unsigned long)got;
      }
      /* 块后 CRLF（缓冲流精确取 2 字节，余量留给下一块 size 行） */
      char crlf[2] = {0, 0};
      size_t have = 0;
      while (have < 2) {
        size_t got = 0;
        int rc = conn_stream(c, (unsigned char *)(crlf + have), 2 - have, &got, resp);
        if (rc == 1) {
          set_err(resp, ATLS_ERR_IO, "connection closed before full response body (EOF)");
          return -1;
        }
        if (rc != 0) {
          return -1;
        }
        have += got;
      }
      if (crlf[0] != '\r' || crlf[1] != '\n') {
        set_err(resp, ATLS_ERR_PROTOCOL, "missing CRLF after chunk");
        return -1;
      }
    }
  }
  if (cl) {
    unsigned long remain = strtoul(cl, NULL, 10);
    while (remain > 0) {
      unsigned char tmp[8192];
      size_t want = sizeof(tmp);
      if (want > remain) {
        want = (size_t)remain;
      }
      size_t got = 0;
      int rc = conn_stream(c, tmp, want, &got, resp);
      if (rc == 1) {
        set_err(resp, ATLS_ERR_IO, "connection closed before full response body (EOF)");
        return -1;
      }
      if (rc != 0) {
        return -1; /* resp->err 已置 */
      }
      if (stream_deliver(cbs, tmp, got, &delivered, resp) != 0) {
        return -1;
      }
      remain -= (unsigned long)got;
    }
    return 0;
  }
  /* 无长度：读至对端关闭（我们发 Connection: close，服务端关连接即收尾） */
  for (;;) {
    unsigned char tmp[8192];
    size_t got = 0;
    int rc = conn_stream(c, tmp, sizeof(tmp), &got, resp);
    if (got > 0 && stream_deliver(cbs, tmp, got, &delivered, resp) != 0) {
      return -1;
    }
    if (rc == 1) {
      return 0; /* 干净关闭 */
    }
    if (rc != 0) {
      return -1; /* resp->err 已置 */
    }
  }
}

/* 执行流式单跳（建连→发送→流式交付最终响应）。
 * 0 = 最终响应流式读完（cbs 已调用，*status_out 填其状态）；
 * 1 = 本跳为 3xx（体已读完丢弃，*loc_out 填 Location 原值，调用方须 free）；
 * -1 = 传输层失败（*out 置错误）。 */
static int do_one_hop_stream(const atls_url *u, const char *method, const atls_request_opts *opts,
                             const unsigned char *body, size_t body_len, int drop_auth,
                             const atls_stream_cbs *cbs, atls_response *out,
                             int *status_out, char **loc_out)
{
  atls_response local;
  memset(&local, 0, sizeof(local));
  kv_vec headers = {0};
  str_vec set_cookies = {0};

  int fd = tcp_connect(u->host, u->port, opts->connect_timeout_ms, opts->cancel, &local);
  if (fd < 0) {
    *out = local;
    return -1;
  }
  atls_conn conn;
  memset(&conn, 0, sizeof(conn));
  conn.fd = fd;
  conn.ssl = NULL;
  conn.wait.cancel = opts->cancel;
  conn.wait.timeout_ms = opts->connect_timeout_ms; /* 写阶段（请求头/体）用建连窗 */
  if (u->is_tls) {
    int64_t deadline = now_ms() + opts->connect_timeout_ms;
    if (tls_handshake(&conn, u->host, deadline, &local) != 0) {
      conn_close(&conn);
      *out = local;
      return -1;
    }
  }
  if (build_and_send_request(&conn, u, method, opts, body, body_len, drop_auth, &local) != 0) {
    conn_close(&conn);
    *out = local;
    return -1;
  }

  /* 读响应（每次读一个独立窗口 = read_timeout_ms；SSE 在此等数据或窗尽） */
  conn.wait.timeout_ms = opts->read_timeout_ms;
  int status = 0;
  if (read_response_head(&conn, &status, &headers, &set_cookies, &local) != 0) {
    conn_close(&conn);
    *out = local;
    kv_free(&headers);
    str_free(&set_cookies);
    return -1;
  }
  while (status == 100) { /* 100-continue：丢弃中间头，读最终响应 */
    kv_free(&headers);
    str_free(&set_cookies);
    if (read_response_head(&conn, &status, &headers, &set_cookies, &local) != 0) {
      conn_close(&conn);
      *out = local;
      kv_free(&headers);
      str_free(&set_cookies);
      return -1;
    }
  }
  int is_redirect = status == 301 || status == 302 || status == 303 ||
                    status == 307 || status == 308;
  if (is_redirect) {
    /* 3xx：体读完丢弃后跟跳（不流式 3xx 体） */
    buf bodybuf = {0};
    int rc = read_response_body(&conn, headers.items, headers.count, status,
                                strcmp(method, "HEAD") == 0, &bodybuf, &local);
    free(bodybuf.data);
    const char *loc = NULL;
    find_header(headers.items, headers.count, "location", &loc);
    conn_close(&conn);
    if (rc != 0) {
      *out = local;
      kv_free(&headers);
      str_free(&set_cookies);
      return -1;
    }
    if (!loc || loc[0] == 0) {
      set_err(&local, ATLS_ERR_PROTOCOL, "redirect %d without location", status);
      *out = local;
      kv_free(&headers);
      str_free(&set_cookies);
      return -1;
    }
    *loc_out = xstrdup(loc);
    if (status_out) {
      *status_out = status;
    }
    kv_free(&headers);
    str_free(&set_cookies);
    return 1;
  }
  if (cbs->on_headers(cbs->ud, status, headers.items, headers.count, set_cookies.items,
                      set_cookies.count) != 0) {
    conn_close(&conn);
    set_err(&local, ATLS_ERR_CANCELLED, "aborted by stream consumer");
    *out = local;
    kv_free(&headers);
    str_free(&set_cookies);
    return -1;
  }
  int rc = read_body_stream(&conn, headers.items, headers.count, status,
                            strcmp(method, "HEAD") == 0, cbs, &local);
  conn_close(&conn);
  kv_free(&headers);
  str_free(&set_cookies);
  if (rc != 0) {
    *out = local;
    return -1;
  }
  if (status_out) {
    *status_out = status;
  }
  return 0;
}

/* 失败面回填（atls_response 错误 → 流式入口的 out 参数） */
static void stream_fail_out(const atls_response *fail, atls_err *out_err, char *err_msg_out,
                            size_t err_msg_cap)
{
  if (out_err) {
    *out_err = fail->err;
  }
  if (err_msg_out && err_msg_cap > 0) {
    snprintf(err_msg_out, err_msg_cap, "%s", fail->err_msg);
  }
}

int atls_request_stream(const atls_request_opts *opts, const atls_stream_cbs *cbs,
                        atls_err *out_err, char *err_msg_out, size_t err_msg_cap)
{
  atls_response fail;
  memset(&fail, 0, sizeof(fail));
  if (!opts || !opts->url || !opts->method || opts->url[0] == 0 || opts->method[0] == 0) {
    set_err(&fail, ATLS_ERR_BAD_URL, "missing url or method");
    stream_fail_out(&fail, out_err, err_msg_out, err_msg_cap);
    return -1;
  }
  const char *cur_method = opts->method;
  const unsigned char *cur_body = opts->body;
  size_t cur_body_len = opts->body_len;
  char *current = xstrdup(opts->url);
  char original_host[ATLS_HOST_BUF] = {0};

  for (int hop = 0; hop <= ATLS_MAX_REDIRECTS; hop++) {
    atls_url u;
    if (parse_url(current, &u) != 0) {
      set_err(&fail, ATLS_ERR_BAD_URL, "bad url: %.160s", current);
      stream_fail_out(&fail, out_err, err_msg_out, err_msg_cap);
      free(current);
      return -1;
    }
    if (hop == 0) {
      snprintf(original_host, sizeof(original_host), "%s", u.host);
    }
    int drop_auth = hop > 0 && strcasecmp(u.host, original_host) != 0;
    atls_response one;
    memset(&one, 0, sizeof(one));
    char *loc = NULL;
    int status = 0;
    int rc = do_one_hop_stream(&u, cur_method, opts, cur_body, cur_body_len, drop_auth, cbs, &one,
                               &status, &loc);
    if (rc == 0) {
      free(current);
      return 0;
    }
    if (rc != 1) {
      stream_fail_out(&one, out_err, err_msg_out, err_msg_cap);
      free(current);
      return -1;
    }
    char *next = resolve_location(loc, &u);
    free(loc);
    free(current);
    if (!next) {
      set_err(&fail, ATLS_ERR_PROTOCOL, "unresolvable redirect location");
      stream_fail_out(&fail, out_err, err_msg_out, err_msg_cap);
      return -1;
    }
    current = next;
    /* httpx 口径：303 恒转 GET 去体；301/302 对 POST 转 GET 去体；307/308 保持 */
    int to_get = status == 303 ||
                 ((status == 301 || status == 302) && strcmp(cur_method, "POST") == 0);
    if (to_get) {
      cur_method = "GET";
      cur_body = NULL;
      cur_body_len = 0;
    }
  }
  set_err(&fail, ATLS_ERR_PROTOCOL, "too many redirects (> %d)", ATLS_MAX_REDIRECTS);
  stream_fail_out(&fail, out_err, err_msg_out, err_msg_cap);
  free(current);
  return -1;
}


void atls_response_free(atls_response *r)
{
  if (!r) {
    return;
  }
  free(r->body);
  if (r->headers) {
    for (size_t i = 0; i < r->header_count * 2; i++) {
      free(r->headers[i]);
    }
    free(r->headers);
  }
  if (r->set_cookies) {
    for (size_t i = 0; i < r->set_cookie_count; i++) {
      free(r->set_cookies[i]);
    }
    free(r->set_cookies);
  }
  memset(r, 0, sizeof(*r));
}

/* ---------------- TLS 探测（诊断页取证） ---------------- */

int atls_tls_probe(const char *host, int port, int timeout_ms, char *protocol_out,
                   size_t protocol_cap, char *cipher_out, size_t cipher_cap, char *err_msg_out,
                   size_t err_msg_cap)
{
  atls_response resp;
  memset(&resp, 0, sizeof(resp));
  int fd = tcp_connect(host, port, timeout_ms, NULL, &resp);
  if (fd < 0) {
    snprintf(err_msg_out, err_msg_cap, "atls:%s: %s", atls_kind_name(resp.err), resp.err_msg);
    return -1;
  }
  atls_conn conn;
  memset(&conn, 0, sizeof(conn));
  conn.fd = fd;
  conn.wait.cancel = NULL;
  int64_t deadline = now_ms() + timeout_ms;
  if (tls_handshake(&conn, host, deadline, &resp) != 0) {
    snprintf(err_msg_out, err_msg_cap, "atls:%s: %s", atls_kind_name(resp.err), resp.err_msg);
    conn_close(&conn);
    return -1;
  }
  if (protocol_out && protocol_cap > 0) {
    snprintf(protocol_out, protocol_cap, "%s", SSL_get_version(conn.ssl));
  }
  if (cipher_out && cipher_cap > 0) {
    snprintf(cipher_out, cipher_cap, "%s", SSL_get_cipher_name(conn.ssl));
  }
  conn_close(&conn);
  return 0;
}

const char *atls_version_string(void)
{
  return OPENSSL_VERSION_TEXT;
}

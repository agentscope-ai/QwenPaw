#!/usr/bin/env python3
"""
gen_cacert.py —— 从系统 Mozilla 根证书包生成 cacert.h

用法:
    python3 gen_cacert.py [输入PEM]   # 默认 /etc/ssl/certs/ca-certificates.crt

产物: 同目录 cacert.h（ATLS_CACERT_PEM + 长度宏）。
更新 CA 包后必须重跑宿主单测（含对 Let's Encrypt 链的 verify=0 实证）再入库。
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "/etc/ssl/certs/ca-certificates.crt"
    with open(src, "rb") as f:
        pem = f.read()
    n = pem.count(b"-----BEGIN CERTIFICATE-----")
    if n < 50:
        print(f"error: only {n} certs in {src}, refusing to generate", file=sys.stderr)
        return 1
    sha = hashlib.sha256(pem).hexdigest()
    today = __import__("datetime").date.today().isoformat()

    lines = [
        "/*",
        " * cacert.h —— 内置 Mozilla 根证书包（CA bundle）",
        " *",
        f" * 来源: {src}（Debian ca-certificates，Mozilla 打包）",
        f" * 抓取日期: {today}",
        f" * 内容: {n} 张根/交叉证书，{len(pem)} 字节，sha256={sha}",
        " *",
        " * 再生成（CA 包过期/增删时更新，流程固定）:",
        " *   python3 gen_cacert.py   # 输入 /etc/ssl/certs/ca-certificates.crt",
        " * 更新后必须重跑宿主单测（含对 Let's Encrypt 链的 verify=0 实证）。",
        " */",
        "#ifndef ATLS_CACERT_H",
        "#define ATLS_CACERT_H",
        "",
        "static const char ATLS_CACERT_PEM[] =",
    ]
    # 相邻字符串字面量拼接不补换行——每个 PEM 行必须自带 \n（末行除外，保持与源字节一致）
    parts = pem.split(b"\n")
    for i, line in enumerate(parts):
        s = line.decode("ascii").replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'"{s}\\n"' if i < len(parts) - 1 else f'"{s}"')
    lines += [
        ";",
        "",
        "#define ATLS_CACERT_PEM_LEN (sizeof(ATLS_CACERT_PEM) - 1)",
        "",
        "#endif /* ATLS_CACERT_H */",
    ]
    out = os.path.join(HERE, "cacert.h")
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"ok: {out} ({n} certs, {len(pem)} bytes, sha256={sha})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

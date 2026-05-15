#!/usr/bin/env python3
"""
Terraform CLI 一键安装与版本检测脚本。

功能：
1. 检测 Terraform 是否已安装
2. 未安装时根据操作系统自动下载安装
3. 输出版本信息确认安装成功

用法：
    python setup_terraform.py [--skip-install] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib import request as urllib_request


HASHICORP_RELEASES = "https://releases.hashicorp.com/terraform"


class SetupResult:
    def __init__(self) -> None:
        self.installed = False
        self.version = ""
        self.binary_path = ""
        self.errors: list[str] = []
        self.actions: list[str] = []

    def summary(self) -> str:
        lines: list[str] = []
        lines.append("=" * 50)
        lines.append("Terraform CLI 安装结果")
        lines.append("=" * 50)

        if self.installed:
            lines.append(f"[OK] Terraform 已安装，版本: {self.version}")
            lines.append(f"[OK] 路径: {self.binary_path}")
        else:
            lines.append("[FAIL] Terraform 未安装")

        if self.errors:
            lines.append("")
            lines.append("错误:")
            for e in self.errors:
                lines.append(f"  - {e}")

        if self.actions:
            lines.append("")
            lines.append("需要您执行的操作:")
            for a in self.actions:
                lines.append(f"  -> {a}")

        lines.append("=" * 50)
        return "\n".join(lines)


def run_cmd(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", "command timed out"


def detect_terraform_binary() -> str | None:
    binary = shutil.which("terraform")
    if binary:
        return binary
    local_bin = Path.home() / ".local" / "bin" / "terraform"
    if local_bin.exists() and os.access(local_bin, os.X_OK):
        return str(local_bin)
    return None


def get_version(binary: str) -> str:
    rc, stdout, _ = run_cmd([binary, "version"])
    if rc == 0 and stdout:
        match = re.search(r"v(\d+\.\d+\.\d+)", stdout)
        if match:
            return match.group(1)
        return stdout.splitlines()[0].strip()
    return ""


def detect_os_arch() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine
    return system, arch


def get_latest_version() -> str:
    try:
        url = "https://checkpoint-api.hashicorp.com/v1/check/terraform"
        req = urllib_request.Request(url, headers={"User-Agent": "terraform-setup/1.0"})
        with urllib_request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("current_version", "1.14.6")
    except Exception:
        return "1.14.6"


def install_via_brew() -> bool:
    if not shutil.which("brew"):
        return False
    print("[setup] 检测到 Homebrew，使用 brew 安装 Terraform ...")
    run_cmd(["brew", "tap", "hashicorp/tap"], timeout=60)
    rc, _, stderr = run_cmd(["brew", "install", "hashicorp/tap/terraform"], timeout=300)
    if rc == 0:
        print("[setup] brew install terraform 成功")
        return True
    print(f"[setup] brew install 失败: {stderr}")
    return False


def install_via_zip(os_name: str, arch: str) -> str | None:
    version = get_latest_version()
    url = f"{HASHICORP_RELEASES}/{version}/terraform_{version}_{os_name}_{arch}.zip"
    install_dir = Path.home() / ".local" / "bin"
    install_dir.mkdir(parents=True, exist_ok=True)
    target = install_dir / "terraform"

    print(f"[setup] 正在从 {url} 下载 Terraform v{version} ...")
    with tempfile.TemporaryDirectory(prefix="terraform-setup-") as td:
        td_path = Path(td)
        zip_path = td_path / "terraform.zip"
        try:
            urllib_request.urlretrieve(url, str(zip_path))
        except Exception as e:
            print(f"[setup] 下载失败: {e}")
            return None

        with zipfile.ZipFile(str(zip_path), "r") as zf:
            zf.extractall(str(td_path))
        extracted = td_path / "terraform"
        if not extracted.exists():
            print("[setup] 解压后未找到 terraform 二进制文件")
            return None
        shutil.copy2(str(extracted), str(target))

    target.chmod(target.stat().st_mode | 0o755)
    print(f"[setup] 已安装到 {target}")
    return str(target)


def install_terraform() -> str | None:
    os_name, arch = detect_os_arch()

    if os_name == "darwin" and install_via_brew():
        binary = shutil.which("terraform")
        if binary:
            return binary

    binary_path = install_via_zip(os_name, arch)
    if binary_path:
        os.environ["PATH"] = str(Path(binary_path).parent) + os.pathsep + os.environ.get("PATH", "")
        return binary_path

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Terraform CLI 一键安装与版本检测")
    parser.add_argument("--skip-install", action="store_true", help="跳过安装步骤")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    args = parser.parse_args()

    result = SetupResult()

    print("[setup] 检测 Terraform 安装状态 ...")
    binary = detect_terraform_binary()

    if binary:
        version = get_version(binary)
        result.installed = True
        result.version = version
        result.binary_path = binary
        print(f"[setup] 已找到 Terraform: {binary} (版本: {version})")
    elif args.skip_install:
        result.errors.append("Terraform 未安装且已跳过安装步骤")
        _output(result, args.json)
        return 1
    else:
        print("[setup] 安装 Terraform ...")
        binary = install_terraform()
        if binary:
            version = get_version(binary)
            result.installed = True
            result.version = version
            result.binary_path = binary
            print(f"[setup] 安装成功: {binary} (版本: {version})")
        else:
            result.errors.append("Terraform 安装失败")
            result.actions.append("请手动安装: brew install hashicorp/tap/terraform")
            result.actions.append("或参照 https://developer.hashicorp.com/terraform/install")
            _output(result, args.json)
            return 1

    _output(result, args.json)
    return 0


def _output(result: SetupResult, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    else:
        print()
        print(result.summary())


if __name__ == "__main__":
    raise SystemExit(main())

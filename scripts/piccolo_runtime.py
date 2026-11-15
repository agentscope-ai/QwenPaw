#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build, package and verify the runtime used by QwenPaw Local."""

import argparse
import configparser
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads(
    (ROOT / "src/qwenpaw/local_models/runtime-release.json").read_text(),
)
PATCH = ROOT / "docs/patches/piccolo-llama.cpp.patch"


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def target_config(target):
    return next(item for item in CONFIG["targets"] if item["id"] == target)


def archive_name(target):
    extension = "zip" if target.startswith("win-") else "tar.gz"
    return f"llama-{CONFIG['release']}-bin-{target}.{extension}"


def identity():
    return {
        key: CONFIG[key]
        for key in ("release", "upstream_commit", "patch_sha256")
    } | {"capabilities": ["chat", "piccolo"]}


def prepare(work):
    if digest(PATCH) != CONFIG["patch_sha256"]:
        raise ValueError(
            "Update the runtime release identity after changing its patch.",
        )
    source = work / "llama.cpp"
    if not source.exists():
        source.mkdir(parents=True)
        run("git", "init", source)
        run("git", "-C", source, "config", "core.autocrlf", "false")
        run(
            "git",
            "-C",
            source,
            "fetch",
            "--depth=1",
            "https://github.com/ggml-org/llama.cpp.git",
            CONFIG["upstream_commit"],
        )
        run("git", "-C", source, "checkout", "--detach", "FETCH_HEAD")
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    if actual != CONFIG["upstream_commit"]:
        raise ValueError(
            "The build directory contains a different llama.cpp revision.",
        )
    applied = (
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "apply",
                "--reverse",
                "--check",
                str(PATCH),
            ],
            capture_output=True,
        ).returncode
        == 0
    )
    if not applied:
        run("git", "-C", source, "apply", "--check", PATCH)
        run("git", "-C", source, "apply", PATCH)
    return source


def install_cuda(version, directory):
    """Install NVIDIA's pinned redistributable toolkit without a driver."""
    base = "https://developer.download.nvidia.com/compute/cuda/redist/"
    with urllib.request.urlopen(
        base + f"redistrib_{version}.json",
        timeout=60,
    ) as response:
        manifest = json.load(response)
    directory.mkdir(parents=True, exist_ok=True)
    components = [
        "cuda_cudart",
        "cuda_nvcc",
        "cuda_nvrtc",
        "libcublas",
        "cuda_cccl",
    ]
    components += [key for key in ("cuda_crt", "libnvvm") if key in manifest]
    for component in components:
        item = manifest[component]["windows-x86_64"]
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "component.zip"
            urllib.request.urlretrieve(base + item["relative_path"], archive)
            if digest(archive) != item["sha256"]:
                raise ValueError(
                    f"NVIDIA package checksum mismatch: {component}",
                )
            with zipfile.ZipFile(archive) as package:
                package.extractall(Path(temporary) / "unpacked")
            roots = list((Path(temporary) / "unpacked").iterdir())
            if len(roots) != 1 or not roots[0].is_dir():
                raise ValueError("Unexpected CUDA package layout")
            for entry in roots[0].iterdir():
                destination = directory / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, destination, dirs_exist_ok=True)
                else:
                    # Keep each component's license when merging toolkits.
                    if (
                        "license" in entry.name.lower()
                        or "eula" in entry.name.lower()
                    ):
                        destination = directory / f"{component}-{entry.name}"
                    shutil.copy2(entry, destination)
    return directory


def build(target, work, output, jobs):
    config = target_config(target)
    source = prepare(work)
    build_dir = work / "build"
    options = [
        "-DCMAKE_BUILD_TYPE=Release",
        "-DGGML_NATIVE=OFF",
        "-DLLAMA_BUILD_UI=OFF",
        "-DLLAMA_OPENSSL=OFF",
        "-DGGML_BACKEND_DL=ON",
        "-DBUILD_SHARED_LIBS=ON",
    ]
    if config["arch"] == "x64":
        options.append("-DGGML_CPU_ALL_VARIANTS=ON")
    cuda = None
    if config["os"] == "macos":
        options += [
            "-DCMAKE_OSX_DEPLOYMENT_TARGET=13.3",
            "-DGGML_METAL=ON",
            "-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON",
            "-DCMAKE_INSTALL_RPATH=@loader_path",
            "-DCMAKE_INSTALL_NAME_DIR=@rpath",
        ]
    elif config["os"] == "linux":
        options += [
            "-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON",
            "-DCMAKE_INSTALL_RPATH=$ORIGIN",
        ]
    else:
        if config["arch"] == "arm64":
            options += [
                "-G",
                "Ninja Multi-Config",
                "-DGGML_OPENMP=OFF",
                f"-DCMAKE_TOOLCHAIN_FILE={source / 'cmake/arm64-windows-llvm.cmake'}",
            ]
        elif config["backend"] != "cuda":
            options += ["-A", "x64"]
        if config["backend"] == "cuda":
            cuda = install_cuda(config["cuda"], work / "cuda")
            options += [
                "-DGGML_CUDA=ON",
                "-G",
                "Ninja Multi-Config",
                f"-DCUDAToolkit_ROOT={cuda}",
                f"-DCMAKE_CUDA_COMPILER={cuda / 'bin/nvcc.exe'}",
                "-DGGML_CUDA_CCCL_VERSION=v3.4.3",
            ]
    run("cmake", "-S", source, "-B", build_dir, *options)
    run(
        "cmake",
        "--build",
        build_dir,
        "--config",
        "Release",
        "--parallel",
        jobs,
        "--target",
        "llama-server",
        "llama-quantize",
        "test-piccolo-layout",
    )
    return package(target, build_dir, source, output, cuda)


def check_macos_libraries(bundle):
    """Keep macOS packages independent of the build machine's libraries."""
    for path in bundle.iterdir():
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\xcf\xfa\xed\xfe":
                continue
        libraries = subprocess.check_output(
            ["otool", "-L", str(path)],
            text=True,
        ).splitlines()[1:]
        for line in libraries:
            library = line.strip().split(" (", 1)[0]
            if library.startswith(("/usr/lib/", "/System/Library/")):
                continue
            for prefix in ("@rpath/", "@loader_path/", "@executable_path/"):
                if library.startswith(prefix):
                    if (bundle / library[len(prefix) :]).is_file():
                        break
            else:
                raise ValueError(
                    f"Unbundled macOS dependency: {path.name} -> {library}",
                )


def package(target, build_dir, source, output, cuda=None):
    config = target_config(target)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        bundle = Path(temporary)
        binaries = build_dir / "bin"
        if (binaries / "Release").is_dir():
            binaries /= "Release"
        for path in binaries.iterdir():
            if path.is_file() and (
                path.name.startswith(
                    (
                        "llama-server",
                        "llama-quantize",
                        "test-piccolo-layout",
                        "ggml-",
                        "libggml",
                        "libllama",
                    ),
                )
                or path.suffix in (".dll", ".dylib", ".metal", ".metallib")
                or ".so" in path.suffixes
            ):
                shutil.copy2(path, bundle / path.name, follow_symlinks=True)
        if config["os"] == "windows":
            redist = Path(os.environ["VCToolsRedistDir"]) / config["arch"]
            for component in ("CRT", "OpenMP"):
                libraries = list(
                    redist.glob(f"Microsoft.VC*.{component}/*.dll"),
                )
                if not libraries and (
                    component == "CRT" or config["arch"] == "x64"
                ):
                    raise ValueError(
                        f"Missing Visual C++ redistributables: {component}",
                    )
                for path in libraries:
                    shutil.copy2(path, bundle / path.name)
        if cuda:
            for pattern in (
                "cudart64_*.dll",
                "cublas64_*.dll",
                "cublasLt64_*.dll",
            ):
                files = list(cuda.rglob(pattern))
                if not files:
                    raise ValueError(
                        f"Missing CUDA runtime dependency: {pattern}",
                    )
                for path in files:
                    shutil.copy2(path, bundle / path.name)
            for path in cuda.iterdir():
                if path.is_file() and any(
                    word in path.name.lower() for word in ("license", "eula")
                ):
                    shutil.copy2(path, bundle / path.name)
        shutil.copy2(source / "LICENSE", bundle / "LICENSE-llama.cpp")
        shutil.copy2(
            source / "licenses/LICENSE-FlexDM",
            bundle / "LICENSE-FlexDM",
        )
        if config["os"] == "macos":
            check_macos_libraries(bundle)
            run(
                "bash",
                ROOT / "scripts/pack-tauri/sign_macos_bundle.sh",
                bundle,
            )
        executable = bundle / (
            "llama-server.exe" if config["os"] == "windows" else "llama-server"
        )
        if not executable.exists():
            raise ValueError("Build did not produce llama-server")
        # Run the packaged binary, with no build-directory working path.
        run(executable, "--version", cwd=bundle)
        metadata = identity() | {
            "target": target,
        }
        (bundle / "qwenpaw-runtime.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
        )
        archive = output / archive_name(target)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as result:
                for path in sorted(bundle.iterdir()):
                    result.write(path, path.name)
        else:
            with tarfile.open(archive, "w:gz", dereference=True) as result:
                for path in sorted(bundle.iterdir()):
                    result.add(path, arcname=path.name)
        (output / (archive.name + ".sha256")).write_text(
            f"{digest(archive)}  {archive.name}\n",
        )
        print(archive)
        return archive


def make_manifest(directory):
    artifacts = {}
    for target in CONFIG["targets"]:
        path = directory / archive_name(target["id"])
        if not path.is_file():
            raise ValueError(f"Missing runtime build: {path.name}")
        checksum = digest(path)
        sidecar = path.with_name(path.name + ".sha256")
        if sidecar.read_text().split()[0] != checksum:
            raise ValueError(f"Local checksum mismatch: {path.name}")
        artifacts[path.name] = {
            "size": path.stat().st_size,
            "sha256": checksum,
        }
    manifest = identity() | {"artifacts": artifacts}
    path = directory / "runtime-release.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify_public(base_url=None, download_dir=None):
    base = (
        (base_url or CONFIG["base_url"]).rstrip("/") + "/" + CONFIG["release"]
    )
    with urllib.request.urlopen(
        base + "/runtime-release.json",
        timeout=30,
    ) as response:
        manifest = json.load(response)
    if any(manifest.get(key) != value for key, value in identity().items()):
        raise ValueError(
            "Published runtime does not match this source revision",
        )
    for target in CONFIG["targets"]:
        name = archive_name(target["id"])
        expected = manifest["artifacts"][name]
        with urllib.request.urlopen(
            base + "/" + name + ".sha256",
            timeout=30,
        ) as response:
            if response.read().decode().split()[0] != expected["sha256"]:
                raise ValueError(f"Published checksum mismatch: {name}")
        request = urllib.request.Request(base + "/" + name, method="HEAD")
        with urllib.request.urlopen(request, timeout=30) as response:
            if int(response.headers["Content-Length"]) != expected["size"]:
                raise ValueError(f"Published size mismatch: {name}")
        if download_dir is not None:
            download_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=download_dir) as temporary:
                downloaded = Path(temporary) / name
                with (
                    urllib.request.urlopen(
                        base + "/" + name,
                        timeout=60,
                    ) as response,
                    downloaded.open("wb") as output,
                ):
                    shutil.copyfileobj(response, output)
                if (
                    downloaded.stat().st_size != expected["size"]
                    or digest(downloaded) != expected["sha256"]
                ):
                    raise ValueError(f"Published checksum mismatch: {name}")
                downloaded.replace(download_dir / name)
            print(f"Verified public download: {name}", flush=True)
    print("All runtime packages are available for this installer version.")


def release_bucket(config_path=None):
    """Use the release environment or an explicitly selected ossutil config."""
    import oss2  # Only the release job needs the OSS SDK.

    if config_path is not None:
        config = configparser.ConfigParser(interpolation=None)
        with config_path.open() as stream:
            config.read_file(stream)
        credentials = config["Credentials"]
        access_id = credentials["accessKeyID"]
        access_secret = credentials["accessKeySecret"]
        token = credentials.get("stsToken")
        endpoint = credentials["endpoint"]
    else:
        access_id = os.environ["OSS_ACCESS_KEY_ID"]
        access_secret = os.environ["OSS_ACCESS_KEY_SECRET"]
        token = os.environ.get("OSS_SESSION_TOKEN")
        endpoint = os.environ["OSS_ENDPOINT"]
    auth = (
        oss2.StsAuth(access_id, access_secret, token)
        if token
        else oss2.Auth(access_id, access_secret)
    )
    return oss2.Bucket(
        auth,
        endpoint if "://" in endpoint else "https://" + endpoint,
        os.environ.get("OSS_BUCKET", "qwenpaw-download"),
    )


def publish(directory, config_path=None):
    """Publish immutable bundles, then the manifest that makes them installable."""
    manifest = make_manifest(directory)
    bucket = release_bucket(config_path)
    prefix = f"files/models/llama_cpp/{CONFIG['release']}/"
    names = list(manifest["artifacts"])
    names += [name + ".sha256" for name in names]
    names += ["runtime-release.json"]
    for name in names:
        path = directory / name
        checksum = digest(path)
        key = prefix + name
        if bucket.object_exists(key):
            metadata = bucket.head_object(key)
            if (
                metadata.headers.get("x-oss-meta-sha256") != checksum
                or metadata.content_length != path.stat().st_size
            ):
                raise ValueError(
                    f"Release object already exists with different bytes: {name}",
                )
        else:
            print(
                f"Uploading {name} ({path.stat().st_size} bytes)",
                flush=True,
            )
            bucket.put_object_from_file(
                key,
                str(path),
                headers={
                    "x-oss-meta-sha256": checksum,
                    "x-oss-object-acl": "public-read",
                },
            )
    verify_public()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("matrix", "build", "manifest", "verify-public", "publish"),
    )
    parser.add_argument(
        "--target",
        choices=[item["id"] for item in CONFIG["targets"]],
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("var/piccolo-runtime-build"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/piccolo-runtime"),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, min(6, os.cpu_count() or 1)),
    )
    parser.add_argument("--base-url")
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument(
        "--oss-config",
        type=Path,
        help="Use this ossutil credentials file instead of release env vars.",
    )
    args = parser.parse_args()
    if args.command == "matrix":
        targets = (
            [target_config(args.target)] if args.target else CONFIG["targets"]
        )
        print(json.dumps({"include": targets}))
    elif args.command == "build":
        if not args.target:
            parser.error("build requires --target")
        build(
            args.target,
            args.work_dir.resolve(),
            args.output.resolve(),
            args.jobs,
        )
    elif args.command == "manifest":
        make_manifest(args.output)
    elif args.command == "verify-public":
        verify_public(args.base_url, args.download_dir)
    elif args.command == "publish":
        publish(args.output, args.oss_config)


if __name__ == "__main__":
    main()

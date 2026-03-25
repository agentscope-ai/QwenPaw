# -*- coding: utf-8 -*-
"""Track C: lightweight resource hints for embedding (no model load)."""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _memory_gb() -> tuple[float | None, float | None]:
    """Return (total_ram_gb, available_ram_gb) or (None, None) if unknown."""
    sys = platform.system()
    try:
        if sys == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            ms = MEMORYSTATUSEX()
            ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                total = ms.ullTotalPhys / (1024.0**3)
                avail = ms.ullAvailPhys / (1024.0**3)
                return (round(total, 2), round(avail, 2))
        if sys == "Linux":
            with open("/proc/meminfo", encoding="utf-8") as f:
                mem_total_kb = None
                mem_avail_kb = None
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_total_kb = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        mem_avail_kb = int(line.split()[1])
                if mem_total_kb is not None:
                    total = mem_total_kb / (1024.0**2)
                    avail = (
                        (mem_avail_kb / (1024.0**2))
                        if mem_avail_kb is not None
                        else None
                    )
                    return (
                        round(total, 2),
                        round(avail, 2) if avail else None,
                    )
        if sys == "Darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if out.returncode == 0 and out.stdout.strip().isdigit():
                total = int(out.stdout.strip()) / (1024.0**3)
                return (round(total, 2), None)
    except Exception as e:
        logger.debug("memory probe failed: %s", e)
    return (None, None)


def _torch_cuda_gpus() -> List[Dict[str, Any]]:
    """GPU list from PyTorch CUDA (no weights loaded)."""
    gpus: List[Dict[str, Any]] = []
    try:
        import torch

        if not torch.cuda.is_available():
            return []
        for i in range(torch.cuda.device_count()):
            name = torch.cuda.get_device_name(i)
            props = torch.cuda.get_device_properties(i)
            total_mb = int(props.total_memory) // (1024 * 1024)
            gpus.append(
                {
                    "index": i,
                    "name": name,
                    "total_memory_mb": total_mb,
                    "source": "torch.cuda",
                },
            )
    except Exception as e:
        logger.debug("torch cuda probe failed: %s", e)
    return gpus


def _nvidia_smi_gpus() -> List[Dict[str, Any]]:
    """Fallback: parse nvidia-smi when torch has no CUDA."""
    nvsmi = shutil.which("nvidia-smi")
    if not nvsmi:
        return []
    try:
        out = subprocess.run(
            [
                nvsmi,
                "--query-gpu=index,name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return []
        gpus: List[Dict[str, Any]] = []
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3 and parts[0].isdigit():
                idx = int(parts[0])
                name = parts[1]
                mem_m = re.search(r"(\d+)", parts[2])
                total_mb = int(mem_m.group(1)) if mem_m else None
                gpus.append(
                    {
                        "index": idx,
                        "name": name,
                        "total_memory_mb": total_mb,
                        "source": "nvidia-smi",
                    },
                )
        return gpus
    except Exception as e:
        logger.debug("nvidia-smi probe failed: %s", e)
        return []


def _gpu_list() -> List[Dict[str, Any]]:
    g = _torch_cuda_gpus()
    if g:
        return g
    return _nvidia_smi_gpus()


def _recommendation_zh(
    total_ram_gb: float | None,
    gpus: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Heuristic suggestions (not a guarantee)."""
    lines: List[str] = []
    max_vram_mb = 0
    if gpus:
        for g in gpus:
            m = g.get("total_memory_mb")
            if isinstance(m, int):
                max_vram_mb = max(max_vram_mb, m)

    ram = total_ram_gb
    if ram is not None and ram < 8:
        lines.append(
            "系统内存偏低（小于 8GB）：建议优先选「纯文本」里的 "
            "`BAAI/bge-small-zh`，设备选 CPU + FP32；不建议使用 2B 多模态。",
        )
    elif ram is not None and ram < 16:
        lines.append(
            "内存约 8–16GB：纯文本可选 `bge-large-zh-v1.5` / `bge-m3`（CPU 可跑，首次加载较慢）；"
            "多模态 2B 更依赖显存，无独显时请谨慎。",
        )
    else:
        lines.append(
            "内存 ≥16GB：纯文本模型选择面较大；多模态仍建议优先有 NVIDIA GPU 与足够显存。",
        )

    if max_vram_mb >= 8 * 1024:
        lines.append(
            "检测到 NVIDIA 显存 ≥8GB：`qwen/Qwen3-VL-Embedding-2B` + FP16 通常可尝试。",
        )
    elif max_vram_mb >= 4 * 1024:
        lines.append(
            "显存约 4–8GB：可尝试多模态 2B 的 FP16；若 OOM，请改小批量或换纯文本模型。",
        )
    elif max_vram_mb > 0:
        lines.append(
            "显存小于 4GB：不建议多模态 2B；请使用纯文本小模型（如 bge-small-zh）或云端 API。",
        )
    elif not gpus:
        lines.append(
            "未检测到可用 NVIDIA GPU：多模态大模型将在 CPU 上极慢；"
            "测试/下载前请优先选「纯文本」模型并把设备设为 CPU。",
        )

    return {
        "summary": " ".join(lines),
        "tiers": {
            "text_small": "BAAI/bge-small-zh（约几百 MB 级权重，最省资源）",
            "text_mid": ("BAAI/bge-large-zh-v1.5 / BAAI/bge-m3（约 1GB+，需更多内存）"),
            "multimodal_2b": (
                "qwen/Qwen3-VL-Embedding-2B（约数 GB，建议 8GB+ 显存或高内存 CPU）"
            ),
        },
    }


def embedding_resource_hint() -> Dict[str, Any]:
    """Return JSON for UI: RAM, GPU, model hints (ADR-003 Track C)."""
    total_ram_gb, avail_ram_gb = _memory_gb()
    gpus = _gpu_list()
    rec = _recommendation_zh(total_ram_gb, gpus)

    note = "以下为未加载权重的环境探测与经验建议；实际占用与批次、序列长度有关。"

    return {
        "platform": platform.system(),
        "cpu_count": os.cpu_count(),
        "ram_total_gb": total_ram_gb,
        "ram_available_gb": avail_ram_gb,
        "gpus": gpus,
        "recommendation": rec["summary"],
        "model_tiers": rec["tiers"],
        "note": note,
    }

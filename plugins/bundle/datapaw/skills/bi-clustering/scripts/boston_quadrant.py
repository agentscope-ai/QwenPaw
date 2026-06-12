# -*- coding: utf-8 -*-
"""波士顿矩阵象限分群：两轴各划低/高两档，输出与聚类脚本一致的 JSON 分组。

输入 CSV：一个分析对象列 + 横轴、纵轴两个特征列（与 skill 数据准备一致）。
连续轴：在有效样本上按 --x-continuous-split / --y-continuous-split 选取平均数（mean）或中位数（median）作为分界：≤ 分界为「低」、> 分界为「高」。离散轴：按取值有序分为前半/后半两组。

象限与 cluster 编号（x 横轴低/高，y 纵轴低/高）：
- cluster 1: x 低, y 低
- cluster 2: x 高, y 低
- cluster 3: x 低, y 高
- cluster 4: x 高, y 高

Usage:
    python boston_quadrant.py \\
        --input-file data.csv \\
        --id-col user_id \\
        --x-col 市场份额 \\
        --y-col 增长率 \\
        --output-json boston.json
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence, Tuple

import numpy as np
import pandas as pd

from json_groups import build_json_from_labels, write_print_json

AXIS_AUTO = "auto"
AXIS_CONT = "continuous"
AXIS_DISC = "discrete"

SPLIT_MEAN = "mean"
SPLIT_MEDIAN = "median"
CONTINUOUS_SPLITS = (SPLIT_MEAN, SPLIT_MEDIAN)


def _is_discrete_series(s: pd.Series, max_uniques: int) -> bool:
    if s.dtype == object or pd.api.types.is_string_dtype(s):
        return True
    if isinstance(s.dtype, pd.CategoricalDtype):
        return True
    nu = s.dropna().nunique()
    return nu <= max_uniques and nu >= 1


def axis_high_mask(
    series: pd.Series,
    mode: str,
    discrete_max_uniques: int,
    continuous_split: str,
) -> Tuple[np.ndarray, str]:
    """
    返回与 series 位置对齐的 bool 数组：True 表示「高」侧。
    同时返回实际采用的模式 resolved_mode（auto 时决出 continuous/discrete）。
    连续轴分界由 continuous_split 指定 mean 或 median；高侧为严格大于分界。
    """
    s = series.reset_index(drop=True)
    m = mode.lower()
    if m not in (AXIS_AUTO, AXIS_CONT, AXIS_DISC):
        raise ValueError(f"Unknown axis mode: {mode}")

    cs = (continuous_split or SPLIT_MEAN).lower()
    if cs not in CONTINUOUS_SPLITS:
        raise ValueError(f"continuous_split must be {CONTINUOUS_SPLITS}, got {continuous_split!r}")

    if m == AXIS_AUTO:
        resolved = AXIS_DISC if _is_discrete_series(s, discrete_max_uniques) else AXIS_CONT
    else:
        resolved = m

    valid = s.notna()
    out = np.full(len(s), False, dtype=bool)

    if resolved == AXIS_CONT:
        sub = pd.to_numeric(s, errors="coerce")
        vals_valid = sub[valid]
        if len(vals_valid) == 0:
            return out, resolved
        if cs == SPLIT_MEAN:
            threshold = float(vals_valid.mean())
        else:
            threshold = float(vals_valid.median())
        vals = sub.to_numpy(dtype=float)
        for pos in range(len(s)):
            if not valid.iloc[pos] or np.isnan(vals[pos]):
                continue
            out[pos] = vals[pos] > threshold
        return out, resolved

    # discrete: rank unique values, first half -> low, second half -> high
    raw = s.where(valid)
    if pd.api.types.is_numeric_dtype(raw.dropna()):
        uniques = sorted(pd.unique(raw.dropna()))
    else:
        uniques = sorted(pd.unique(raw.dropna()), key=lambda x: str(x))
    if not uniques:
        return out, resolved
    n = len(uniques)
    if n == 1:
        low_set, high_set = set(uniques), set()
    else:
        mid = n // 2
        low_set = set(uniques[:mid])
        high_set = set(uniques[mid:])
    for pos, v in enumerate(s.values):
        if pd.isna(v):
            continue
        out[pos] = v in high_set
    return out, resolved


def quadrant_labels(x_high: np.ndarray, y_high: np.ndarray) -> np.ndarray:
    """cluster 1..4 约定见模块 docstring；若某一维缺失(False/False 占位)由 NaN 行处理。"""
    xb = x_high.astype(np.int8)
    yb = y_high.astype(np.int8)
    # 1 + x + 2*y: (0,0)->1 (1,0)->2 (0,1)->3 (1,1)->4
    return 1 + xb + 2 * yb


def run_boston(
    df: pd.DataFrame,
    id_col: str,
    x_col: str,
    y_col: str,
    x_mode: str,
    y_mode: str,
    discrete_max_uniques: int,
    x_continuous_split: str,
    y_continuous_split: str,
) -> Tuple[pd.DataFrame, str, str, np.ndarray]:
    miss = [c for c in (id_col, x_col, y_col) if c not in df.columns]
    if miss:
        raise ValueError(f"Missing columns in CSV: {miss}")

    work = df[[id_col, x_col, y_col]].copy()
    before = len(work)
    work = work.dropna(subset=[x_col, y_col])
    dropped = before - len(work)
    if dropped:
        print(f"dropped {dropped} row(s) with NaN in axis columns", file=sys.stderr)

    x_high, x_res = axis_high_mask(work[x_col], x_mode, discrete_max_uniques, x_continuous_split)
    y_high, y_res = axis_high_mask(work[y_col], y_mode, discrete_max_uniques, y_continuous_split)
    labs = quadrant_labels(x_high, y_high)
    meta_x = f"{x_col}:{x_res}" + (f":{x_continuous_split}" if x_res == AXIS_CONT else "")
    meta_y = f"{y_col}:{y_res}" + (f":{y_continuous_split}" if y_res == AXIS_CONT else "")
    return work, meta_x, meta_y, labs


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Boston matrix 2x2 quadrant grouping -> JSON")
    p.add_argument("--input-file", required=True)
    p.add_argument("--id-col", required=True)
    p.add_argument("--x-col", required=True, help="Horizontal axis column")
    p.add_argument("--y-col", required=True, help="Vertical axis column")
    p.add_argument(
        "--x-mode",
        default=AXIS_AUTO,
        choices=[AXIS_AUTO, AXIS_CONT, AXIS_DISC],
        help="How to split x axis (default: auto)",
    )
    p.add_argument(
        "--y-mode",
        default=AXIS_AUTO,
        choices=[AXIS_AUTO, AXIS_CONT, AXIS_DISC],
        help="How to split y axis (default: auto)",
    )
    p.add_argument(
        "--discrete-max-uniques",
        type=int,
        default=12,
        help="auto: numeric column with <= this many distinct values is treated as discrete",
    )
    p.add_argument(
        "--x-continuous-split",
        default=SPLIT_MEAN,
        choices=list(CONTINUOUS_SPLITS),
        help="Threshold on x when x is continuous: mean or median (default: mean)",
    )
    p.add_argument(
        "--y-continuous-split",
        default=SPLIT_MEAN,
        choices=list(CONTINUOUS_SPLITS),
        help="Threshold on y when y is continuous: mean or median (default: mean)",
    )
    p.add_argument("--output-json", required=True)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argparser().parse_args(list(argv) if argv is not None else None)
    try:
        df = pd.read_csv(args.input_file)
        work, mx, my, labels = run_boston(
            df,
            args.id_col,
            args.x_col,
            args.y_col,
            args.x_mode,
            args.y_mode,
            args.discrete_max_uniques,
            args.x_continuous_split,
            args.y_continuous_split,
        )
        ids = work[args.id_col].values
        # build_json_from_labels 约定 sklearn 式 0..K-1 -> cluster 1..K；象限标签已为 1..4
        payload = build_json_from_labels(ids, labels - 1)
        ordered: dict = {f"cluster {i}": payload.get(f"cluster {i}", []) for i in range(1, 5)}
        write_print_json(args.output_json, ordered)
        print(f"axes: {mx}; {my}", file=sys.stderr)
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Compute LTV from user-level or group-level CSV per bi-ltv-analysis SKILL.md.

Output CSV: column 1 = analysis object (--object-col), column 2 = LTV (--ltv-col).
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

import pandas as pd


def _to_churn(value: float, rate_is_retention: bool) -> float:
    if pd.isna(value):
        return float("nan")
    v = float(value)
    if rate_is_retention:
        return 1.0 - v
    return v


def _row_arpu(row: pd.Series, revenue_col: str, users_col: str | None) -> float:
    rev = row[revenue_col]
    if pd.isna(rev):
        return float("nan")
    if users_col:
        users = row[users_col]
        if pd.isna(users) or float(users) <= 0:
            return float("nan")
        return float(rev) / float(users)
    return float(rev)


def ltv_cumulative(row: pd.Series, revenue_cols: Sequence[str]) -> float:
    """用户级：观测窗口内各阶段收入之和。"""
    vals = [row[c] for c in revenue_cols]
    if all(pd.isna(v) for v in vals):
        return float("nan")
    return float(pd.Series(vals, dtype=float).fillna(0).sum())


def ltv_lifecycle(
    row: pd.Series,
    revenue_col: str,
    lifecycle: float,
    users_col: str | None,
) -> float:
    """公式一：LTV = ARPU × 生命周期。"""
    arpu = _row_arpu(row, revenue_col, users_col)
    if pd.isna(arpu):
        return float("nan")
    return arpu * lifecycle


def ltv_churn(
    row: pd.Series,
    revenue_col: str,
    churn_col: str,
    users_col: str | None,
    rate_is_retention: bool,
) -> float:
    """公式二：LTV = ARPU × (1 / 流失率)。"""
    arpu = _row_arpu(row, revenue_col, users_col)
    if pd.isna(arpu):
        return float("nan")
    churn = _to_churn(row[churn_col], rate_is_retention)
    if pd.isna(churn) or churn <= 0:
        return float("nan")
    return arpu / churn


def ltv_stage_weighted(
    row: pd.Series,
    revenue_cols: Sequence[str],
    churn_cols: Sequence[str],
    rate_is_retention: bool,
) -> float:
    """群体级多阶段：LTV = Σ 阶段收入 × 到达该阶段前的存活率。"""
    survival = 1.0
    total = 0.0
    has_value = False
    for churn_col, rev_col in zip(churn_cols, revenue_cols):
        rev = row[rev_col]
        if not pd.isna(rev):
            total += float(rev) * survival
            has_value = True
        churn = _to_churn(row[churn_col], rate_is_retention)
        if pd.isna(churn):
            churn = 0.0
        survival *= 1.0 - float(churn)
    return total if has_value else float("nan")


def infer_formula(
    revenue_cols: Sequence[str] | None,
    churn_cols: Sequence[str] | None,
    churn_col: str | None,
    revenue_col: str | None,
    lifecycle: float | None,
) -> str:
    if churn_cols and revenue_cols:
        if len(churn_cols) != len(revenue_cols):
            raise ValueError("--churn-cols 与 --revenue-cols 数量须一致。")
        return "stage_weighted"
    if lifecycle is not None and revenue_col:
        return "lifecycle"
    if churn_col and revenue_col:
        return "churn"
    if revenue_cols:
        return "cumulative"
    raise ValueError(
        "无法推断计算方式：请指定 --revenue-cols（用户级累计），"
        "或 --revenue-cols 与 --churn-cols（群体多阶段），"
        "或 --revenue-col 与 --lifecycle / --churn-col。"
    )


def compute_ltv_series(
    df: pd.DataFrame,
    object_col: str,
    formula: str,
    revenue_cols: Sequence[str] | None,
    churn_cols: Sequence[str] | None,
    revenue_col: str | None,
    churn_col: str | None,
    lifecycle: float | None,
    users_col: str | None,
    rate_is_retention: bool,
) -> pd.Series:
    if formula == "cumulative":
        assert revenue_cols
        return df.apply(
            lambda r: ltv_cumulative(r, revenue_cols), axis=1
        )
    if formula == "stage_weighted":
        assert revenue_cols and churn_cols
        return df.apply(
            lambda r: ltv_stage_weighted(r, revenue_cols, churn_cols, rate_is_retention),
            axis=1,
        )
    if formula == "lifecycle":
        assert revenue_col and lifecycle is not None
        return df.apply(
            lambda r: ltv_lifecycle(r, revenue_col, lifecycle, users_col),
            axis=1,
        )
    if formula == "churn":
        assert revenue_col and churn_col
        return df.apply(
            lambda r: ltv_churn(r, revenue_col, churn_col, users_col, rate_is_retention),
            axis=1,
        )
    raise ValueError(f"Unknown formula: {formula}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="根据 CSV 计算 LTV，并写出「分析对象列 + LTV」两列结果。"
    )
    parser.add_argument("--input-file", required=True, help="输入 CSV 路径")
    parser.add_argument(
        "--object-col",
        required=True,
        help="分析对象列名（如用户ID、群体类别）",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="输出 CSV 路径（两列：分析对象、LTV）",
    )
    parser.add_argument(
        "--ltv-col",
        default="ltv",
        help="输出 CSV 中 LTV 列名（默认 ltv）",
    )
    parser.add_argument(
        "--formula",
        choices=("cumulative", "lifecycle", "churn", "stage_weighted"),
        default=None,
        help="计算方式；省略时按参数自动推断",
    )
    parser.add_argument(
        "--revenue-cols",
        nargs="+",
        default=None,
        help="多阶段收入列名（用户级累计或群体多阶段）",
    )
    parser.add_argument(
        "--churn-cols",
        nargs="+",
        default=None,
        help="多阶段流失率列名，与 --revenue-cols 一一对应",
    )
    parser.add_argument("--revenue-col", default=None, help="单列收入（公式一/二）")
    parser.add_argument("--churn-col", default=None, help="单列流失率（公式二）")
    parser.add_argument(
        "--lifecycle",
        type=float,
        default=None,
        help="生命周期数值 T（公式一：LTV = ARPU × T）",
    )
    parser.add_argument(
        "--users-col",
        default=None,
        help="用户数列；收入为阶段合计时用于 ARPU = 收入/用户数",
    )
    parser.add_argument(
        "--rate-is-retention",
        action="store_true",
        help="流失率列实际为留存率时，按 流失率=1-留存率 转换",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.input_file)
    if args.object_col not in df.columns:
        print(f"Error: object column '{args.object_col}' not in CSV.", file=sys.stderr)
        sys.exit(1)

    revenue_cols = args.revenue_cols
    if revenue_cols is None and args.revenue_col:
        revenue_cols = [args.revenue_col]

    try:
        formula = args.formula or infer_formula(
            revenue_cols,
            args.churn_cols,
            args.churn_col,
            args.revenue_col,
            args.lifecycle,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    revenue_col = args.revenue_col
    if formula in ("lifecycle", "churn") and not revenue_col and revenue_cols:
        revenue_col = revenue_cols[0]

    if formula == "cumulative" and not revenue_cols:
        print("Error: --revenue-cols required for cumulative formula.", file=sys.stderr)
        sys.exit(1)
    if formula == "stage_weighted" and (not revenue_cols or not args.churn_cols):
        print(
            "Error: --revenue-cols and --churn-cols required for stage_weighted.",
            file=sys.stderr,
        )
        sys.exit(1)
    if formula == "lifecycle" and (revenue_col is None or args.lifecycle is None):
        print(
            "Error: --revenue-col and --lifecycle required for lifecycle formula.",
            file=sys.stderr,
        )
        sys.exit(1)
    if formula == "churn" and (revenue_col is None or args.churn_col is None):
        print(
            "Error: --revenue-col and --churn-col required for churn formula.",
            file=sys.stderr,
        )
        sys.exit(1)

    ltv = compute_ltv_series(
        df,
        args.object_col,
        formula,
        revenue_cols,
        args.churn_cols,
        revenue_col,
        args.churn_col,
        args.lifecycle,
        args.users_col,
        args.rate_is_retention,
    )

    out = pd.DataFrame({args.object_col: df[args.object_col], args.ltv_col: ltv.round(6)})
    out.to_csv(args.output_file, index=False)

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", None)
    print(f"formula: {formula}")
    print(out.to_string(index=False))
    print(f"Wrote {args.output_file}", file=sys.stderr)


if __name__ == "__main__":
    main()

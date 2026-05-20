# -*- coding: utf-8 -*-
"""归因计算脚本

支持4种归因方法：
- 量值-标准法 (quantity-standard): 增量/总增量
- 量值-正负分离法 (quantity-separate): 正负贡献分别归一
- 率值-保留交叉项法 (ratio-cross-term): 结构效应+水平效应+交互效应
- 率值-平均权重法 (ratio-average): 两因素平均权重分解

支持单维度和多维度交叉分析。多维度时自动拼接为组合维度列。

Usage (命令行):
    # 单维度 - 量值标准法
    python contribution_calc.py \\
        --input-file data.csv \\
        --dimension "渠道" \\
        --history-col "销售额_往期" \\
        --current-col "销售额_当期" \\
        --method quantity-standard

    # 多维度交叉
    python contribution_calc.py \\
        --input-file data.csv \\
        --dimension "渠道" "端类型" \\
        --history-col "销售额_往期" \\
        --current-col "销售额_当期" \\
        --method quantity-standard

    # 率值归因
    python contribution_calc.py \\
        --input-file data.csv \\
        --dimension "渠道" \\
        --history-col "转化率_往期" \\
        --current-col "转化率_当期" \\
        --numerator-history "转化人数_往期" \\
        --numerator-current "转化人数_当期" \\
        --denominator-history "访问人数_往期" \\
        --denominator-current "访问人数_当期" \\
        --method ratio-cross-term

Usage (Python 导入):
    from contribution_calc import calculate_contribution
    result = calculate_contribution(
        df=df,
        target_dimensions=["渠道"],
        history_col="销售额_往期",
        current_col="销售额_当期",
        method="quantity-standard"
    )
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Tuple

import pandas as pd


# ============================================================
# 维度预处理
# ============================================================

def _prepare_dimension(
    df: pd.DataFrame,
    dimensions: List[str],
    history_col: str,
    current_col: str,
    ratio_cols: Optional[Tuple[str, str, str, str]] = None,
) -> Tuple[pd.DataFrame, str]:
    """多维度时拼接为组合维度列，并按组合维度聚合数据。

    单维度时直接返回原始数据。

    Args:
        df: 原始数据
        dimensions: 维度列名列表
        history_col: 往期值列名
        current_col: 当期值列名
        ratio_cols: (分子往期列, 分子当期列, 分母往期列, 分母当期列)

    Returns:
        Tuple[pd.DataFrame, str]: (处理后的数据, 最终维度列名)
    """
    if len(dimensions) == 1:
        return df, dimensions[0]

    # 多维度：拼接为组合维度列
    dim_col = "_".join(dimensions)
    df = df.copy()
    df[dim_col] = df[dimensions].astype(str).agg("_".join, axis=1)

    # 确定需要聚合的数值列
    agg_cols = {history_col: "sum", current_col: "sum"}
    if ratio_cols:
        for col in ratio_cols:
            agg_cols[col] = "sum"

    # 按组合维度聚合
    df = df.groupby(dim_col, as_index=False).agg(agg_cols)

    # 率值/加权平均：聚合后需重新计算指标值
    if ratio_cols:
        numer_hist, numer_curr, denom_hist, denom_curr = ratio_cols
        df[history_col] = df[numer_hist] / df[denom_hist]
        df[current_col] = df[numer_curr] / df[denom_curr]

    return df, dim_col


# ============================================================
# 量值指标归因
# ============================================================

def calculate_quantity_standard(
    df: pd.DataFrame,
    target_dimension: str,
    history_col: str,
    current_col: str,
) -> pd.DataFrame:
    """量值指标归因 - 标准法

    公式: 贡献度 = (当期值 - 往期值) / 总增量 × 100%
    """
    df = df.copy()
    df.fillna(0.0, inplace=True)

    df["增量"] = df[current_col] - df[history_col]
    total_inc = round(df["增量"].sum())

    if total_inc == 0:
        raise ValueError("指标总增量为 0，无须归因。")

    df["贡献度"] = df["增量"] * 100.0 / total_inc

    result = df[[target_dimension, history_col, current_col, "增量", "贡献度"]]
    result = result.sort_values(by=["贡献度"], key=abs, ascending=False)

    result["增量"] = result["增量"].apply(lambda x: f"{x:.0f}")
    result["总增量"] = total_inc
    result["贡献度"] = result["贡献度"].apply(lambda x: f"{x:.2f}%")

    return result


def calculate_quantity_separate(
    df: pd.DataFrame,
    target_dimension: str,
    history_col: str,
    current_col: str,
) -> pd.DataFrame:
    """量值指标归因 - 正负分离法

    正负贡献分别归一化，避免相互抵消掩盖真实驱动因素。
    """
    df = df.copy()
    df.fillna(0.0, inplace=True)

    df["增量"] = df[current_col] - df[history_col]
    total_inc = df["增量"].sum()

    positive_sum = df[df["增量"] > 0]["增量"].sum()
    negative_sum = abs(df[df["增量"] < 0]["增量"].sum())

    df["正向贡献率"] = df.apply(
        lambda row: row["增量"] * 100.0 / positive_sum if row["增量"] > 0 else 0, axis=1
    )
    df["负向贡献率"] = df.apply(
        lambda row: row["增量"] * 100.0 / negative_sum if row["增量"] < 0 else 0, axis=1
    )

    max_directional_change = max(positive_sum, negative_sum)
    separation_needed = max_directional_change > abs(total_inc) * 0.3 if total_inc != 0 else False

    result = df[[target_dimension, history_col, current_col, "增量", "正向贡献率", "负向贡献率"]]
    result = result.sort_values(by=["增量"], key=abs, ascending=False)

    result["增量"] = result["增量"].apply(lambda x: f"{x:.0f}")
    result["总增量"] = round(total_inc)
    result["正向贡献率"] = result["正向贡献率"].apply(lambda x: f"{x:.2f}%" if x != 0 else "-")
    result["负向贡献率"] = result["负向贡献率"].apply(lambda x: f"{x:.2f}%" if x != 0 else "-")
    result["分离建议"] = "是" if separation_needed else "否"

    return result


# ============================================================
# 率值/加权平均指标归因
# ============================================================

def calculate_ratio_cross_term(
    df: pd.DataFrame,
    target_dimension: str,
    history_col: str,
    current_col: str,
    ratio_cols: Tuple[str, str, str, str],
) -> pd.DataFrame:
    """率值/加权平均指标归因 - 保留交叉项法

    公式:
    - 结构效应 = (wᵢ₁ - wᵢ₀) × rᵢ₀
    - 水平效应 = wᵢ₁ × (rᵢ₁ - rᵢ₀)
    - 交互效应 = (wᵢ₁ - wᵢ₀) × (rᵢ₁ - rᵢ₀)
    """
    numer_hist, numer_curr, denom_hist, denom_curr = ratio_cols
    df = df.copy()
    df.fillna(0.0, inplace=True)

    total_history = df[denom_hist].sum()
    total_current = df[denom_curr].sum()

    df["权重_往期"] = df[denom_hist] / total_history
    df["权重_当期"] = df[denom_curr] / total_current

    df["结构效应"] = (df["权重_当期"] - df["权重_往期"]) * df[history_col]
    df["水平效应"] = df["权重_当期"] * (df[current_col] - df[history_col])
    df["交互效应"] = (df["权重_当期"] - df["权重_往期"]) * (df[current_col] - df[history_col])
    df["总贡献"] = df["结构效应"] + df["水平效应"] + df["交互效应"]

    cols = [
        target_dimension, history_col, current_col,
        "权重_往期", "权重_当期",
        "结构效应", "水平效应", "交互效应", "总贡献"
    ]
    result = df[cols].sort_values(by=["总贡献"], key=abs, ascending=False).head(10)

    result[history_col] = result[history_col].apply(lambda x: f"{x:.2f}pt")
    result[current_col] = result[current_col].apply(lambda x: f"{x:.2f}pt")
    result["权重_往期"] = result["权重_往期"].apply(lambda x: f"{x * 100:.2f}%")
    result["权重_当期"] = result["权重_当期"].apply(lambda x: f"{x * 100:.2f}%")
    result["结构效应"] = result["结构效应"].apply(lambda x: f"{x:.2f}pt")
    result["水平效应"] = result["水平效应"].apply(lambda x: f"{x:.2f}pt")
    result["交互效应"] = result["交互效应"].apply(lambda x: f"{x:.2f}pt")
    result["总贡献"] = result["总贡献"].apply(lambda x: f"{x:.2f}pt")

    return result


def calculate_ratio_average(
    df: pd.DataFrame,
    target_dimension: str,
    history_col: str,
    current_col: str,
    ratio_cols: Tuple[str, str, str, str],
) -> pd.DataFrame:
    """率值/加权平均指标归因 - 平均权重法

    公式:
    - 结构效应 = (wᵢ₁ - wᵢ₀) × (rᵢ₀ + rᵢ₁) / 2
    - 水平效应 = (rᵢ₁ - rᵢ₀) × (wᵢ₀ + wᵢ₁) / 2
    """
    numer_hist, numer_curr, denom_hist, denom_curr = ratio_cols
    df = df.copy()
    df.fillna(0.0, inplace=True)

    total_history = df[denom_hist].sum()
    total_current = df[denom_curr].sum()

    df["权重_往期"] = df[denom_hist] / total_history
    df["权重_当期"] = df[denom_curr] / total_current

    avg_rate = (df[history_col] + df[current_col]) / 2
    avg_weight = (df["权重_往期"] + df["权重_当期"]) / 2

    df["结构效应"] = (df["权重_当期"] - df["权重_往期"]) * avg_rate
    df["水平效应"] = (df[current_col] - df[history_col]) * avg_weight
    df["总贡献"] = df["结构效应"] + df["水平效应"]

    cols = [
        target_dimension, history_col, current_col,
        "权重_往期", "权重_当期",
        "结构效应", "水平效应", "总贡献"
    ]
    result = df[cols].sort_values(by=["总贡献"], key=abs, ascending=False).head(10)

    result[history_col] = result[history_col].apply(lambda x: f"{x:.2f}pt")
    result[current_col] = result[current_col].apply(lambda x: f"{x:.2f}pt")
    result["权重_往期"] = result["权重_往期"].apply(lambda x: f"{x * 100:.2f}%")
    result["权重_当期"] = result["权重_当期"].apply(lambda x: f"{x * 100:.2f}%")
    result["结构效应"] = result["结构效应"].apply(lambda x: f"{x:.2f}pt")
    result["水平效应"] = result["水平效应"].apply(lambda x: f"{x:.2f}pt")
    result["总贡献"] = result["总贡献"].apply(lambda x: f"{x:.2f}pt")

    return result


# ============================================================
# 统一入口
# ============================================================

def calculate_contribution(
    df: pd.DataFrame,
    target_dimensions: List[str],
    history_col: str,
    current_col: str,
    method: str = "quantity-standard",
    numerator_history: Optional[str] = None,
    numerator_current: Optional[str] = None,
    denominator_history: Optional[str] = None,
    denominator_current: Optional[str] = None,
) -> pd.DataFrame:
    """归因计算统一入口

    Args:
        df: 数据文件
        target_dimensions: 维度列名列表
        history_col: 往期值列名
        current_col: 当期值列名
        method: 归因方法
        numerator_history: 分子往期列名（率值/加权平均指标时必填）
        numerator_current: 分子当期列名
        denominator_history: 分母往期列名
        denominator_current: 分母当期列名

    Returns:
        pd.DataFrame: 归因结果表格
    """
    # 构建 ratio_cols
    ratio_cols = None
    has_ratio = any(x is not None for x in [numerator_history, numerator_current, denominator_history, denominator_current])
    if has_ratio:
        if not all(x is not None for x in [numerator_history, numerator_current, denominator_history, denominator_current]):
            raise ValueError("率值/加权平均指标需同时指定 numerator_history、numerator_current、denominator_history、denominator_current")
        ratio_cols = (numerator_history, numerator_current, denominator_history, denominator_current)

    # 维度预处理
    df, dim_col = _prepare_dimension(df, target_dimensions, history_col, current_col, ratio_cols)

    method_map = {
        "quantity-standard": calculate_quantity_standard,
        "quantity-separate": calculate_quantity_separate,
        "ratio-cross-term": calculate_ratio_cross_term,
        "ratio-average": calculate_ratio_average,
    }

    if method not in method_map:
        raise ValueError(f"不支持的归因方法: {method}。可选: {list(method_map.keys())}")

    if method.startswith("ratio-") and not ratio_cols:
        raise ValueError(f"方法 {method} 需要指定分子分母列（--numerator-history/--numerator-current/--denominator-history/--denominator-current）")

    if not method.startswith("ratio-") and ratio_cols:
        raise ValueError(f"方法 {method} 不需要分子分母列参数")

    if method.startswith("ratio-"):
        return method_map[method](df, dim_col, history_col, current_col, ratio_cols)
    else:
        return method_map[method](df, dim_col, history_col, current_col)


# ============================================================
# 命令行入口
# ============================================================

def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="归因计算工具 - 支持4种归因方法，支持多维度交叉")
    parser.add_argument("--input-file", required=True, help="输入数据文件路径 (CSV)")
    parser.add_argument("--dimension", required=True, nargs="+", help="维度列名，支持多个")
    parser.add_argument("--history-col", required=True, help="往期值列名")
    parser.add_argument("--current-col", required=True, help="当期值列名")
    parser.add_argument(
        "--method",
        choices=["quantity-standard", "quantity-separate", "ratio-cross-term", "ratio-average"],
        default="quantity-standard",
        help="归因方法 (默认: quantity-standard)"
    )

    # 率值/加权平均指标的分子分母列
    parser.add_argument("--numerator-history", default=None, help="分子往期列名（率值/加权平均指标时必填）")
    parser.add_argument("--numerator-current", default=None, help="分子当期列名（率值/加权平均指标时必填）")
    parser.add_argument("--denominator-history", default=None, help="分母往期列名（率值/加权平均指标时必填）")
    parser.add_argument("--denominator-current", default=None, help="分母当期列名（率值/加权平均指标时必填）")

    parser.add_argument("--output-file", default="", help="输出文件路径 (可选)")

    args = parser.parse_args()

    try:
        df = pd.read_csv(args.input_file)

        result = calculate_contribution(
            df=df,
            target_dimensions=args.dimension,
            history_col=args.history_col,
            current_col=args.current_col,
            method=args.method,
            numerator_history=args.numerator_history,
            numerator_current=args.numerator_current,
            denominator_history=args.denominator_history,
            denominator_current=args.denominator_current,
        )

        if result.empty:
            print("无归因结果")
            sys.exit(1)

        if args.output_file:
            result.to_csv(args.output_file, index=False, encoding="utf-8")
            print(f"结果已保存到: {args.output_file}")
        else:
            print(f"\n{'=' * 60}")
            print(f"归因结果 - 方法: {args.method}")
            if len(args.dimension) > 1:
                print(f"组合维度: {' × '.join(args.dimension)}")
            print("=" * 60)
            print(result.to_string(index=False))

    except FileNotFoundError as e:
        print(f"文件不存在: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"参数错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

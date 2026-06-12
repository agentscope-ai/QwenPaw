from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path

import pandas as pd


def compute_basic_stats(
    df: pd.DataFrame,
    value_col: str,
) -> dict[str, list]:
    ser = df[value_col]
    mean = float(ser.mean().round(5))
    std = float(ser.std().round(5))
    median = float(ser.median().round(5))
    return {
        "均值": [mean],
        "标准差": [std],
        "中位数": [median],
    }


def compute_top_5_stats(
    df: pd.DataFrame,
    value_col: str,
    dimension_col: str,
) -> dict[str, list]:
    ser = df[value_col]
    sum_value = ser.sum()
    top_5_stats = df.sort_values(by=value_col, ascending=False).head(5)
    top_5_values = top_5_stats[dimension_col].values.tolist()
    per_top_5_values_ratio = (top_5_stats[value_col] / sum_value).round(5).tolist()
    return {
        "top_5_国家": top_5_values,
        "top_5_国家占比": per_top_5_values_ratio,
    }


def compute_frequency_analysis(
    df: pd.DataFrame,
    value_col: str,
    dimension_col: str,
) -> dict[str, dict[str, list]]:
    """按累计占比对维度分组。

    将各维度按 value_col 从大到小排序，计算每个维度的累计占比 r
    （= 截至该维度的累计数值 / 所有维度数值之和），按 r 落入以下 7 个桶：

      "<0.5", "[0.5, 0.6)", "[0.6, 0.7)", "[0.7, 0.8)",
      "[0.8, 0.9)", "[0.9, 0.95)", ">=0.95"
    """
    bin_labels = [
        "<0.5",
        "[0.5, 0.6)",
        "[0.6, 0.7)",
        "[0.7, 0.8)",
        "[0.8, 0.9)",
        "[0.9, 0.95)",
        ">=0.95",
    ]
    buckets: dict[str, list] = {label: [] for label in bin_labels}

    if len(df) == 0:
        return {"频率分布": buckets}

    sorted_df = df.sort_values(by=value_col, ascending=False).reset_index(drop=True)
    total = float(sorted_df[value_col].sum())
    if total <= 0:
        return {"频率分布": buckets}

    cum_ratio = (sorted_df[value_col].cumsum() / total).tolist()
    dims = sorted_df[dimension_col].tolist()

    for dim, r in zip(dims, cum_ratio):
        if r < 0.5:
            label = "<0.5"
        elif r < 0.6:
            label = "[0.5, 0.6)"
        elif r < 0.7:
            label = "[0.6, 0.7)"
        elif r < 0.8:
            label = "[0.7, 0.8)"
        elif r < 0.9:
            label = "[0.8, 0.9)"
        elif r < 0.95:
            label = "[0.9, 0.95)"
        else:
            label = ">=0.95"
        buckets[label].append(dim)

    return {"频率分布": buckets}


def write_result(stats: dict[str, list], save_file: Path):
    if save_file.exists():
        with open(save_file, "r", encoding="utf-8") as f:
            result = json.load(f)
        result["results"].update(stats)
    else:
        result = {
            "results": stats,
        }
    with open(save_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def main() -> None:
    p = argparse.ArgumentParser(description="分布分析：均值、方差、标准差；可选等宽分箱")
    p.add_argument("--input_file", required=True, help="输入 CSV 路径")
    p.add_argument("--value_col", required=True, help="数值列名")
    p.add_argument("--dimension_col", required=True, help="区间维度列名")
    args = p.parse_args()

    try:
        path = Path(args.input_file)
        df = pd.read_csv(path, encoding="utf-8-sig")
        basic_stats = compute_basic_stats(df, args.value_col)
        top_5_stats = compute_top_5_stats(df, args.value_col, args.dimension_col)
        freq_stats = compute_frequency_analysis(df, args.value_col, args.dimension_col)
        stats = {**basic_stats, **top_5_stats, **freq_stats}
        write_result(stats, Path("result.json"))
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        print(f"已写入 {Path('result.json')}")
    except FileNotFoundError as e:
        print(f"输入文件不存在: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"参数错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"数据分布分析失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

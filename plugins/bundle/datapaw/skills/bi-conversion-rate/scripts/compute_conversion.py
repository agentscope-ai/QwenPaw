"""Aggregate conversion rate: sum(end) / sum(begin)."""

import argparse
import sys
import json
from pathlib import Path

import pandas as pd


def compute_conversion(
    df: pd.DataFrame,
    begin_col: str,
    end_col: str,
) -> pd.Series:
    return (df[end_col] / df[begin_col]).round(5)


def write_result(conversion: pd.Series, metric_name: str, save_file: Path):
    if save_file.exists():
        with open(save_file, "r", encoding="utf-8") as f:
            result = json.load(f)
        result["results"][metric_name] = conversion.to_list()
    else:
        result = {
            "results": {
                metric_name: conversion.to_list(),
            }
        }
    with open(save_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="计算转化率（结束阶段用户合计 / 起始阶段用户合计）")
    parser.add_argument("--input_file", required=True, help="输入数据文件路径 (CSV)")
    parser.add_argument("--metric_name", required=True, help="计算指标名称")
    parser.add_argument("--begin_col", required=True, help="起始阶段用户数列名")
    parser.add_argument("--end_col", required=True, help="结束阶段用户数列名")
    args = parser.parse_args()

    try:
        df = pd.read_csv(args.input_file)
        conversion = compute_conversion(df, args.begin_col, args.end_col)
        write_result(conversion, args.metric_name, Path("result.json"))
        conversion_result = {f"{args.metric_name}": conversion.to_list()}
        print(json.dumps(conversion_result, ensure_ascii=False, indent=2))
        print(f"已写入 {Path('result.json')}")
    except FileNotFoundError as e:
        print(f"输入文件不存在: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"参数或数据错误: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"计算失败: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

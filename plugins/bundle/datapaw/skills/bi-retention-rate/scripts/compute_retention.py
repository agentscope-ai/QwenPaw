import sys
import json
import argparse
from pathlib import Path
import pandas as pd


def compute_retention(
    df: pd.DataFrame,
    day0_col: str,
    dayn_col: str,
) -> pd.Series:
    return (df[dayn_col] / df[day0_col]).round(5)


def write_result(retention: pd.Series, metric_name: str, save_file: Path):
    if save_file.exists():
        with open(save_file, "r", encoding="utf-8") as f:
            result = json.load(f)
        result["results"][metric_name] = retention.to_list()
    else:
        result = {
            "results": {
                metric_name: retention.to_list(),
            }
        }
    with open(save_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="计算留存率")
    parser.add_argument("--input_file", required=True, help="输入数据文件路径 (CSV)")
    parser.add_argument("--metric_name", required=True, help="计算指标名称")
    parser.add_argument("--day0_col", required=True, help="第0天用户数列名")
    parser.add_argument("--dayn_col", required=True, help="第n天用户数列名")
    args = parser.parse_args()
    
    try:
        df = pd.read_csv(args.input_file)
        retention = compute_retention(df, args.day0_col, args.dayn_col)
        write_result(retention, args.metric_name, Path("result.json"))
        retention_result = {f"{args.metric_name}": retention.to_list()}
        print(json.dumps(retention_result, ensure_ascii=False, indent=2))
        print(f"已写入 {Path('result.json')}")
    except FileNotFoundError as e:
        print(f"输入文件不存在: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"参数错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"计算事件统计结果失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

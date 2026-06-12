# TODO: Implement metric computation according to the given data

import argparse
import pandas as pd


def compute_event_per_user(
    df: pd.DataFrame,
    event_occurrence_col: str,
    event_user_col: str,
) -> float:
    pass


def compute_event_penetration(
    df: pd.DataFrame,
    event_user_col: str,
    target_user_col: str,
) -> float:
    pass


def main():
    parser = argparse.ArgumentParser(description="计算事件统计结果")
    parser.add_argument("--input-file", required=True, help="输入数据文件路径 (CSV)")
    parser.add_argument("--event-occurrence-col", required=True, help="事件发生次数列名")
    parser.add_argument("--event-user-col", required=True, help="事件发生用户数列名")
    parser.add_argument("--target-user-col", required=True, help="目标用户数列名")
    args = parser.parse_args()
    
    try:
        df = pd.read_csv(args.input-file)
        df = df.groupby(args.event-occurrence-col).agg({args.event-user-col: "sum"}).reset_index()
        event_per_user = compute_event_per_user(df, args.event-occurrence-col, args.event-user-col)
        event_penetration = compute_event_penetration(df, args.event-user-col, args.target-user-col)
        print(f"人均事件发生次数: {event_per_user}")
        print(f"目标用户群体功能使用渗透率: {event_penetration}")
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

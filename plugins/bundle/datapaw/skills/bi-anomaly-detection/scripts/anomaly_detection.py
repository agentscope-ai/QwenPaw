# -*- coding: utf-8 -*-
"""异常波动点识别脚本

基于阈值识别时间序列中的显著异常波动点。
传入哪些阈值参数，就计算哪些变化率并检测异常；传入多个阈值时，异常点取交集。

Usage (命令行):
    # 只检查日环比
    python anomaly_detection.py \\
        --input-file data.csv \\
        --date-col "日期" \\
        --metric-col "访问用户数" \\
        --threshold-dod 0.10

    # 同时检查日环比和周同比（异常点取交集）
    python anomaly_detection.py \\
        --input-file data.csv \\
        --date-col "日期" \\
        --metric-col "访问用户数" \\
        --threshold-dod 0.10 \\
        --threshold-wow 0.15

    # 检查月环比
    python anomaly_detection.py \\
        --input-file data.csv \\
        --date-col "日期" \\
        --metric-col "访问用户数" \\
        --threshold-mom 0.20

Usage (Python 导入):
    from anomaly_detection import detect_anomalies

    full_df, anomalies_df = detect_anomalies(
        df, date_col="日期", metric_col="访问用户数",
        threshold_dod=0.10, threshold_wow=0.15
    )
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Tuple

import pandas as pd


# ============================================================
# 异常波动点识别
# ============================================================

def detect_anomalies(
    df: pd.DataFrame,
    date_col: str,
    metric_col: str,
    threshold_dod: Optional[float] = None,
    threshold_wow: Optional[float] = None,
    threshold_woq: Optional[float] = None,
    threshold_mom: Optional[float] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """异常波动点识别

    根据传入的阈值参数决定计算哪些变化率：
    - threshold_dod: 日环比（日数据，与前一天对比）
    - threshold_wow: 周同比（日数据，与上周同日对比）
    - threshold_woq: 周环比（周数据，与上周对比）
    - threshold_mom: 月环比（月数据，与上月对比）

    传入多个阈值时，异常点取交集（所有变化率都超阈值才算异常）。

    Args:
        df: 时间序列数据，包含日期列和指标列
        date_col: 日期列名
        metric_col: 指标列名
        threshold_dod: 日环比阈值，传入则检查日环比
        threshold_wow: 周同比阈值，传入则检查周同比
        threshold_woq: 周环比阈值，传入则检查周环比
        threshold_mom: 月环比阈值，传入则检查月环比

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (完整数据, 异常波动点列表)
    """
    # 至少需要传入一个阈值
    if all(t is None for t in [threshold_dod, threshold_wow, threshold_woq, threshold_mom]):
        raise ValueError("至少需要传入一个阈值参数（threshold_dod/threshold_wow/threshold_woq/threshold_mom）")

    df = df.copy()

    # 1. 数据准备
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)

    conditions = []
    check_info = []

    # 2. 根据传入的阈值参数计算对应的变化率
    if threshold_dod is not None:
        # 日环比：与前一天对比
        df['dod_rate'] = df[metric_col].pct_change()
        conditions.append(df['dod_rate'].abs() >= threshold_dod)
        check_info.append(f"日环比>={threshold_dod:.0%}")

    if threshold_wow is not None:
        # 周同比：与上周同日对比（日数据，shift 7）
        df['wow_rate'] = df[metric_col].pct_change(periods=7)
        conditions.append(df['wow_rate'].abs() >= threshold_wow)
        check_info.append(f"周同比>={threshold_wow:.0%}")

    if threshold_woq is not None:
        # 周环比：与上周对比（周数据，shift 1）
        df['woq_rate'] = df[metric_col].pct_change()
        conditions.append(df['woq_rate'].abs() >= threshold_woq)
        check_info.append(f"周环比>={threshold_woq:.0%}")

    if threshold_mom is not None:
        # 月环比：与上月对比（月数据，shift 1）
        df['mom_rate'] = df[metric_col].pct_change()
        conditions.append(df['mom_rate'].abs() >= threshold_mom)
        check_info.append(f"月环比>={threshold_mom:.0%}")

    # 3. 异常判定：所有条件取交集
    df['is_anomaly'] = conditions[0]
    for condition in conditions[1:]:
        df['is_anomaly'] = df['is_anomaly'] & condition

    # 4. 提取异常波动点
    anomalies_df = df[df['is_anomaly']].copy()

    # 格式化变化率为百分比
    rate_cols = ['dod_rate', 'wow_rate', 'woq_rate', 'mom_rate']
    for col in rate_cols:
        if col in df.columns:
            pct_col = col + '_pct'
            df[pct_col] = df[col].apply(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "")
            if not anomalies_df.empty:
                anomalies_df[pct_col] = anomalies_df[col].apply(lambda x: f"{x*100:+.2f}%")

    return df, anomalies_df


# ============================================================
# 命令行入口
# ============================================================

def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="异常波动点识别工具")
    parser.add_argument("--input-file", required=True, help="输入数据文件路径 (CSV)")
    parser.add_argument("--date-col", required=True, help="日期列名")
    parser.add_argument("--metric-col", required=True, help="指标列名")

    # 阈值参数：传入哪些就检查哪些，至少传一个
    parser.add_argument("--threshold-dod", type=float, default=None, help="日环比阈值，传入则检查日环比")
    parser.add_argument("--threshold-wow", type=float, default=None, help="周同比阈值，传入则检查周同比")
    parser.add_argument("--threshold-woq", type=float, default=None, help="周环比阈值，传入则检查周环比")
    parser.add_argument("--threshold-mom", type=float, default=None, help="月环比阈值，传入则检查月环比")

    # 输出路径
    parser.add_argument("--output-file", default="", help="异常波动点输出路径 (可选)")

    args = parser.parse_args()

    # 检查至少传入一个阈值
    if all(t is None for t in [args.threshold_dod, args.threshold_wow, args.threshold_woq, args.threshold_mom]):
        parser.error("至少需要传入一个阈值参数（--threshold-dod/--threshold-wow/--threshold-woq/--threshold-mom）")

    try:
        # 读取数据文件
        df = pd.read_csv(args.input_file)

        # 检查必要列
        if args.date_col not in df.columns:
            raise ValueError(f"日期列 '{args.date_col}' 不存在于数据文件中")
        if args.metric_col not in df.columns:
            raise ValueError(f"指标列 '{args.metric_col}' 不存在于数据文件中")

        # 执行异常识别
        full_df, anomalies_df = detect_anomalies(
            df=df,
            date_col=args.date_col,
            metric_col=args.metric_col,
            threshold_dod=args.threshold_dod,
            threshold_wow=args.threshold_wow,
            threshold_woq=args.threshold_woq,
            threshold_mom=args.threshold_mom,
        )

        # 输出结果
        if args.output_file:
            if anomalies_df.empty:
                print("\n警告: 未发现异常波动点")
            else:
                anomalies_df.to_csv(args.output_file, index=False, encoding="utf-8")
                print(f"\n异常波动点已保存到: {args.output_file}")

        # 打印摘要
        enabled = []
        if args.threshold_dod is not None:
            enabled.append(f"日环比阈值: {args.threshold_dod:.0%}")
        if args.threshold_wow is not None:
            enabled.append(f"周同比阈值: {args.threshold_wow:.0%}")
        if args.threshold_woq is not None:
            enabled.append(f"周环比阈值: {args.threshold_woq:.0%}")
        if args.threshold_mom is not None:
            enabled.append(f"月环比阈值: {args.threshold_mom:.0%}")

        print(f"\n检查项: {', '.join(enabled)}")
        print(f"数据行数: {len(full_df)}")
        print(f"异常波动点数: {len(anomalies_df)}")

        if not anomalies_df.empty:
            print("\n异常波动点:")
            display_cols = [args.date_col, args.metric_col]
            for col in ['dod_rate_pct', 'wow_rate_pct', 'woq_rate_pct', 'mom_rate_pct']:
                if col in anomalies_df.columns:
                    display_cols.append(col)
            print(anomalies_df[display_cols].to_string(index=False))

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

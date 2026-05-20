# -*- coding: utf-8 -*-
"""自适应阈值计算脚本

基于 Ruptures 变化点检测的自适应阈值计算。

Usage (命令行):
    python adaptive_threshold.py \\
        --input-file data.csv \\
        --date-col "date" \\
        --metric-col "访问用户数" \\
        --output-threshold threshold.json

输入文件格式 (CSV):
    必须包含日期列和指标列，数据已按目标粒度处理好:
    date,访问用户数
    2025-01-01,10000
    2025-01-02,10500
    2025-01-03,9800

Usage (Python 导入):
    from adaptive_threshold import calculate_adaptive_threshold
    
    threshold_result = calculate_adaptive_threshold(
        df, 
        date_col="date", 
        metric_col="value"
    )
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# 尝试导入 ruptures，未安装时给出提示
try:
    import ruptures as rpt
except ImportError:
    print("错误: 请先安装 ruptures 库: pip install ruptures")
    sys.exit(1)


# ============================================================
# 数据预处理
# ============================================================

def preprocess_data(
    df: pd.DataFrame,
    date_col: str,
    metric_col: str,
) -> pd.DataFrame:
    """数据预处理

    Args:
        df: 原始数据
        date_col: 日期列名
        metric_col: 指标列名

    Returns:
        pd.DataFrame: 处理后的数据
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)

    return df


# ============================================================
# IQR 异常值剔除
# ============================================================

def remove_outliers_iqr(
    values: pd.Series,
    iqr_multiplier: float = 1.5,
) -> pd.Series:
    """使用 IQR 方法剔除异常值

    Step 3: 剔除变化率中的极端异常值

    Args:
        values: 数值序列
        iqr_multiplier: IQR 倍数

    Returns:
        pd.Series: 剔除异常值后的序列
    """
    if len(values) < 4:
        return values

    q1 = values.quantile(0.25)
    q3 = values.quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - iqr_multiplier * iqr
    upper_bound = q3 + iqr_multiplier * iqr

    return values[(values >= lower_bound) & (values <= upper_bound)]


# ============================================================
# Ruptures 变化点检测
# ============================================================

def detect_change_points_ruptures(
    change_rates: np.ndarray,
    method: str = "pelt",
    penalty: Optional[float] = None,
) -> List[int]:
    """使用 Ruptures 检测变化点

    Step 4: 变化点检测

    Args:
        change_rates: 变化率序列
        method: 检测方法 (pelt/binseg/window)
        penalty: 惩罚系数，None 则自动计算

    Returns:
        List[int]: 变化点索引列表（包含起始和结束点）
    """
    # 数据标准化，便于 ruptures 处理
    data = change_rates.reshape(-1, 1)

    # 自动计算惩罚系数
    if penalty is None:
        # 基于数据量的启发式惩罚
        penalty = np.log(len(change_rates))

    # 选择检测算法
    if method == "pelt":
        algo = rpt.Pelt(model="l2", min_size=2).fit(data)
    elif method == "binseg":
        algo = rpt.Binseg(model="l2", min_size=2).fit(data)
    elif method == "window":
        algo = rpt.Window(width=10, model="l2").fit(data)
    else:
        raise ValueError(f"不支持的检测方法: {method}")

    # 检测变化点
    change_points = algo.predict(pen=penalty)

    # 确保包含起始点 0
    if 0 not in change_points:
        change_points = [0] + change_points

    return change_points


def segment_data(
    change_rates: pd.Series,
    change_points: List[int],
) -> List[Tuple[int, int, pd.Series]]:
    """根据变化点划分数据分段

    Args:
        change_rates: 变化率序列
        change_points: 变化点索引列表

    Returns:
        List[Tuple[int, int, pd.Series]]: 分段列表 [(start, end, segment_data), ...]
    """
    segments = []
    for i in range(len(change_points) - 1):
        start = change_points[i]
        end = change_points[i + 1]
        segment = change_rates.iloc[start:end]
        segments.append((start, end, segment))

    return segments


# ============================================================
# 阈值计算
# ============================================================

def calculate_threshold_with_range(
    std: float,
    std_multiplier: float,
    threshold_min: float,
    threshold_max: float,
) -> float:
    """计算阈值并限制范围

    Step 6: 阈值 = 标准差 × std_multiplier，然后限制在 [min, max] 范围内

    Args:
        std: 标准差
        std_multiplier: 标准差倍数
        threshold_min: 阈值下限
        threshold_max: 阈值上限

    Returns:
        float: 最终阈值
    """
    threshold = std * std_multiplier
    return max(threshold_min, min(threshold, threshold_max))


# ============================================================
# 主函数：自适应阈值计算
# ============================================================

def calculate_adaptive_threshold(
    df: pd.DataFrame,
    date_col: str,
    metric_col: str,
    min_periods: int = 30,
    iqr_multiplier: float = 1.5,
    std_multiplier: float = 3.0,
    threshold_min: float = 0.05,
    threshold_max: float = 0.20,
    default_threshold: float = 0.10,
    ruptures_method: str = "pelt",
    ruptures_penalty: Optional[float] = None,
) -> Dict:
    """计算自适应阈值

    完整流程:
    1. 数据预处理
    2. 检查数据量（数据周期数 < min_periods → 返回默认阈值）
    3. 计算变化率 → IQR 剔除异常值
    4. Ruptures 变化点检测
    5. 计算最后一段标准差，判断稳定性（标准差 ≥ threshold_max → fallback）
    6. 计算阈值并限制范围

    Args:
        df: 时间序列数据
        date_col: 日期列名
        metric_col: 指标列名
        min_periods: 最少数据天数
        iqr_multiplier: IQR 倍数
        std_multiplier: 标准差倍数
        threshold_min: 阈值下限
        threshold_max: 阈值上限
        default_threshold: 默认阈值
        ruptures_method: 变化点检测方法
        ruptures_penalty: 惩罚系数

    Returns:
        Dict: 阈值计算结果
    """
    # Step 1: 数据预处理
    processed_df = preprocess_data(df, date_col, metric_col)
    data_periods = len(processed_df)

    # Step 2: 检查数据量
    if data_periods < min_periods:
        return {
            "阶段": "初期兜底",
            "数据充足": False,
            "数据周期数": data_periods,
            "需要周期数": min_periods,
            "使用阈值": default_threshold,
            "说明": f"数据不足（{data_periods} < {min_periods}），使用默认阈值"
        }

    # Step 3: 计算变化率 + IQR 剔除异常值
    change_rates = processed_df[metric_col].pct_change().dropna()

    if len(change_rates) < min_periods:
        return {
            "阶段": "初期兜底",
            "数据充足": False,
            "数据周期数": len(change_rates),
            "需要周期数": min_periods,
            "使用阈值": default_threshold,
            "说明": f"有效数据不足（{len(change_rates)} < {min_periods}），使用默认阈值"
        }

    # IQR 剔除异常值
    filtered_rates = remove_outliers_iqr(change_rates, iqr_multiplier)

    # Step 4: Ruptures 变化点检测
    change_points = detect_change_points_ruptures(
        filtered_rates.values,
        method=ruptures_method,
        penalty=ruptures_penalty,
    )

    # Step 5: 划分分段并计算最后一段标准差
    segments = segment_data(filtered_rates, change_points)

    # 构建分段信息
    segment_info = []
    for start, end, segment in segments:
        segment_std = segment.std()
        segment_info.append({
            "区间": f"{start+1}-{end}",
            "标准差": round(segment_std, 4),
        })

    # 获取最后一段
    last_start, last_end, last_segment = segments[-1]
    last_std = last_segment.std()

    # 判断稳定性：最后一段标准差 ≥ threshold_max 视为波动剧烈
    if last_std >= threshold_max:
        return {
            "阶段": "波动剧烈",
            "数据充足": True,
            "数据周期数": data_periods,
            "有效周期数": len(filtered_rates),
            "检测到的分段": segment_info,
            "最后分段": f"{last_start+1}-{last_end}",
            "标准差": round(last_std, 4),
            "使用阈值": default_threshold,
            "说明": f"最后分段({last_start+1}-{last_end})波动剧烈（标准差 {last_std*100:.2f}% ≥ {threshold_max*100:.0f}%），使用默认阈值"
        }

    # Step 6: 计算阈值并限制范围
    threshold = calculate_threshold_with_range(
        last_std,
        std_multiplier,
        threshold_min,
        threshold_max,
    )

    return {
        "阶段": "分段计算",
        "数据充足": True,
        "数据周期数": data_periods,
        "有效周期数": len(filtered_rates),
        "检测到的分段": segment_info,
        "最后分段": f"{last_start+1}-{last_end}",
        "标准差": round(last_std, 4),
        "使用阈值": round(threshold, 4),
        "说明": f"Ruptures检测到{len(segments)}个分段，最后分段({last_start+1}-{last_end})标准差{last_std*100:.2f}%，阈值{threshold*100:.2f}%"
    }


# ============================================================
# 命令行入口
# ============================================================

def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="自适应阈值计算脚本（基于 Ruptures 变化点检测）")
    parser.add_argument("--input-file", required=True, help="输入数据文件路径 (CSV)")
    parser.add_argument("--date-col", required=True, help="日期列名")
    parser.add_argument("--metric-col", required=True, help="指标列名")

    # 数据范围参数
    parser.add_argument("--min-periods", type=int, default=30, help="最少数据天数 (默认: 30)")

    # IQR 参数
    parser.add_argument("--iqr-multiplier", type=float, default=1.5, help="IQR 倍数 (默认: 1.5)")

    # 阈值计算参数
    parser.add_argument("--std-multiplier", type=float, default=3.0, help="标准差倍数 (默认: 3.0)")
    parser.add_argument("--threshold-min", type=float, default=0.05, help="阈值下限 (默认: 0.05)")
    parser.add_argument("--threshold-max", type=float, default=0.20, help="阈值上限 (默认: 0.20)")
    parser.add_argument("--default-threshold", type=float, default=0.10, help="默认阈值 (默认: 0.10)")

    # Ruptures 参数
    parser.add_argument("--ruptures-method", type=str, default="pelt",
                        choices=["pelt", "binseg", "window"],
                        help="变化点检测方法 (默认: pelt)")
    parser.add_argument("--ruptures-penalty", type=float, default=None,
                        help="惩罚系数 (默认: 自动计算)")



    args = parser.parse_args()

    try:
        # 读取数据文件
        df = pd.read_csv(args.input_file)

        # 检查必要列
        if args.date_col not in df.columns:
            raise ValueError(f"日期列 '{args.date_col}' 不存在于数据文件中")
        if args.metric_col not in df.columns:
            raise ValueError(f"指标列 '{args.metric_col}' 不存在于数据文件中")

        # 计算自适应阈值
        threshold_result = calculate_adaptive_threshold(
            df=df,
            date_col=args.date_col,
            metric_col=args.metric_col,
            min_periods=args.min_periods,
            iqr_multiplier=args.iqr_multiplier,
            std_multiplier=args.std_multiplier,
            threshold_min=args.threshold_min,
            threshold_max=args.threshold_max,
            default_threshold=args.default_threshold,
            ruptures_method=args.ruptures_method,
            ruptures_penalty=args.ruptures_penalty,
        )

        # 打印精简结果
        stage = threshold_result['阶段']
        threshold = threshold_result['使用阈值']

        if stage == '初期兜底':
            print(f"threshold: {threshold} (数据不足，使用默认阈值)")
        elif stage == '波动剧烈':
            print(f"threshold: {threshold} (波动剧烈，使用默认阈值)")
        else:
            print(f"threshold: {threshold}")

    except FileNotFoundError as e:
        print(f"文件不存在: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"参数错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

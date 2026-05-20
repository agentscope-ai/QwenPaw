#!/usr/bin/env python3
"""时间因素波动归因脚本

将指标月度波动拆解为结构变动、趋势变动和事件影响。
"""

import argparse
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd


def is_workday(date: datetime) -> bool:
    """判断是否为工作日（周一到周五）"""
    return date.weekday() < 5


def get_event_date_range(
    start_date: str,
    end_date: str,
    event_type: str = "event",
    holiday_lead_days: int = 1,
    event_lag_days: int = 2,
) -> List[datetime]:
    """获取事件影响的时间范围
    
    节假日：假期开始前 holiday_lead_days 天 ~ 假期结束
    事件波动：事件开始当天 ~ 事件开始后 event_lag_days 天
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    if event_type == "holiday":
        # 节假日：前 holiday_lead_days 天开始
        start = start - timedelta(days=holiday_lead_days)
        return [start + timedelta(days=i) for i in range((end - start).days + 1)]
    else:
        # 事件波动：开始后 event_lag_days 天
        end = start + timedelta(days=event_lag_days)
        return [start + timedelta(days=i) for i in range(event_lag_days + 1)]


def calculate_baseline(
    df: pd.DataFrame,
    date_col: str,
    metric_col: str,
    month: str,
    exclude_dates: Optional[set] = None,
) -> Tuple[float, float, int, int]:
    """计算指定月份的工作日/非工作日基线
    
    Returns:
        (工作日基线, 非工作日基线, 工作日天数, 非工作日天数)
    """
    month_start = datetime.strptime(month, "%Y-%m")
    if month_start.month == 12:
        month_end = datetime(month_start.year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = datetime(month_start.year, month_start.month + 1, 1) - timedelta(days=1)
    
    # 筛选当月数据
    df_month = df[
        (df[date_col] >= month_start) & (df[date_col] <= month_end)
    ].copy()
    
    if exclude_dates:
        df_month = df_month[~df_month[date_col].isin(exclude_dates)]
    
    # 按工作日/非工作日分组
    df_month["is_workday"] = df_month[date_col].apply(is_workday)
    
    workday_df = df_month[df_month["is_workday"]]
    nonworkday_df = df_month[~df_month["is_workday"]]
    
    workday_baseline = workday_df[metric_col].mean() if len(workday_df) > 0 else 0
    nonworkday_baseline = nonworkday_df[metric_col].mean() if len(nonworkday_df) > 0 else 0
    workday_count = len(workday_df)
    nonworkday_count = len(nonworkday_df)
    
    return workday_baseline, nonworkday_baseline, workday_count, nonworkday_count


def calculate_event_impact(
    df: pd.DataFrame,
    date_col: str,
    metric_col: str,
    event_dates: List[datetime],
    workday_baseline: float,
    nonworkday_baseline: float,
) -> Tuple[float, float, int, int]:
    """计算事件影响度
    
    Returns:
        (影响度, 事件均值影响, 事件工作日天数, 事件非工作日天数)
    """
    event_dates_set = set(event_dates)
    df_event = df[df[date_col].isin(event_dates_set)].copy()
    
    if len(df_event) == 0:
        return 0.0, 0.0, 0, 0
    
    df_event["is_workday"] = df_event[date_col].apply(is_workday)
    
    event_workday_df = df_event[df_event["is_workday"]]
    event_nonworkday_df = df_event[~df_event["is_workday"]]
    
    event_workday_mean = event_workday_df[metric_col].mean() if len(event_workday_df) > 0 else workday_baseline
    event_nonworkday_mean = event_nonworkday_df[metric_col].mean() if len(event_nonworkday_df) > 0 else nonworkday_baseline
    
    event_workday_count = len(event_workday_df)
    event_nonworkday_count = len(event_nonworkday_df)
    
    # 计算影响度
    numerator = (
        event_workday_count * (event_workday_mean - workday_baseline) +
        event_nonworkday_count * (event_nonworkday_mean - nonworkday_baseline)
    )
    denominator = (
        event_workday_count * workday_baseline +
        event_nonworkday_count * nonworkday_baseline
    )
    
    if denominator == 0:
        impact_ratio = 0.0
    else:
        impact_ratio = numerator / denominator
    
    # 计算事件均值影响（用于后续拆解）
    event_impact = numerator
    
    return impact_ratio, event_impact, event_workday_count, event_nonworkday_count


def calculate_event_final_impact(
    df: pd.DataFrame,
    date_col: str,
    metric_col: str,
    event_dates: List[datetime],
    workday_baseline: float,
    nonworkday_baseline: float,
    month_days: int,
    is_current_month: bool = True,
) -> float:
    """计算事件的最终影响值
    
    当月事件：事件i影响 = (事件i工作日天数*(事件i工作日均值-当月工作日基线)
                         + 事件i非工作日天数*(事件i非工作日均值-当月非工作日基线)) / 当月天数
    上月事件：事件i影响 = ((0-事件i工作日天数)*(事件i工作日均值-当月工作日基线)
                         + (0-事件i非工作日天数)*(事件i非工作日均值-当月非工作日基线)) / 上月天数
    """
    event_dates_set = set(event_dates)
    df_event = df[df[date_col].isin(event_dates_set)].copy()
    
    if len(df_event) == 0:
        return 0.0
    
    df_event["is_workday"] = df_event[date_col].apply(is_workday)
    
    event_workday_df = df_event[df_event["is_workday"]]
    event_nonworkday_df = df_event[~df_event["is_workday"]]
    
    event_workday_mean = event_workday_df[metric_col].mean() if len(event_workday_df) > 0 else workday_baseline
    event_nonworkday_mean = event_nonworkday_df[metric_col].mean() if len(event_nonworkday_df) > 0 else nonworkday_baseline
    
    event_workday_count = len(event_workday_df)
    event_nonworkday_count = len(event_nonworkday_df)
    
    if is_current_month:
        impact = (
            event_workday_count * (event_workday_mean - workday_baseline) +
            event_nonworkday_count * (event_nonworkday_mean - nonworkday_baseline)
        ) / month_days
    else:
        impact = (
            -event_workday_count * (event_workday_mean - workday_baseline) +
            -event_nonworkday_count * (event_nonworkday_mean - nonworkday_baseline)
        ) / month_days
    
    return impact


def run_attribution(
    df: pd.DataFrame,
    date_col: str,
    metric_col: str,
    events_df: Optional[pd.DataFrame],
    current_month: str,
    prev_month: str,
    impact_threshold: float = 0.10,
    holiday_lead_days: int = 1,
    event_lag_days: int = 2,
) -> Dict:
    """执行波动归因分析"""
    
    # 确保日期列为 datetime 类型
    df[date_col] = pd.to_datetime(df[date_col])
    
    # 获取所有事件日期
    all_event_dates: set = set()
    events_info: List[Dict] = []
    
    if events_df is not None and len(events_df) > 0:
        for _, row in events_df.iterrows():
            event_name = row.get("event_name", "unknown")
            start_date = row["start_date"]
            end_date = row["end_date"]
            event_type = row.get("event_type", "event")
            
            event_dates = get_event_date_range(
                start_date, end_date, event_type,
                holiday_lead_days, event_lag_days
            )
            all_event_dates.update(event_dates)
            
            events_info.append({
                "name": event_name,
                "type": event_type,
                "dates": event_dates,
                "start_date": start_date,
                "end_date": end_date,
            })
    
    # Step 1: 计算初始基线（不含任何事件日）
    curr_workday_baseline, curr_nonworkday_baseline, curr_workday_count, curr_nonworkday_count = \
        calculate_baseline(df, date_col, metric_col, current_month, all_event_dates)
    
    prev_workday_baseline, prev_nonworkday_baseline, prev_workday_count, prev_nonworkday_count = \
        calculate_baseline(df, date_col, metric_col, prev_month, all_event_dates)
    
    # Step 2: 计算各事件影响度，确定哪些需要剔除
    events_to_exclude: set = set()
    events_impact_info: List[Dict] = []
    
    for event in events_info:
        # 判断事件属于哪个月
        event_start = datetime.strptime(event["start_date"], "%Y-%m-%d")
        current_month_start = datetime.strptime(current_month, "%Y-%m")
        prev_month_start = datetime.strptime(prev_month, "%Y-%m")
        
        if event_start >= current_month_start:
            # 当月事件
            impact_ratio, _, _, _ = calculate_event_impact(
                df, date_col, metric_col, event["dates"],
                curr_workday_baseline, curr_nonworkday_baseline
            )
            event_month = "current"
        else:
            # 上月事件
            impact_ratio, _, _, _ = calculate_event_impact(
                df, date_col, metric_col, event["dates"],
                prev_workday_baseline, prev_nonworkday_baseline
            )
            event_month = "previous"
        
        event["impact_ratio"] = impact_ratio
        event["event_month"] = event_month
        events_impact_info.append(event)
        
        # 影响度超过阈值，需要从基线计算中剔除
        if abs(impact_ratio) > impact_threshold:
            events_to_exclude.update(event["dates"])
    
    # Step 3: 确定最终基线（剔除大事件后重新计算）
    curr_workday_baseline_final, curr_nonworkday_baseline_final, curr_workday_count_final, curr_nonworkday_count_final = \
        calculate_baseline(df, date_col, metric_col, current_month, events_to_exclude)
    
    prev_workday_baseline_final, prev_nonworkday_baseline_final, prev_workday_count_final, prev_nonworkday_count_final = \
        calculate_baseline(df, date_col, metric_col, prev_month, events_to_exclude)
    
    # 计算月度总指标
    curr_month_start = datetime.strptime(current_month, "%Y-%m")
    if curr_month_start.month == 12:
        curr_month_end = datetime(curr_month_start.year + 1, 1, 1) - timedelta(days=1)
    else:
        curr_month_end = datetime(curr_month_start.year, curr_month_start.month + 1, 1) - timedelta(days=1)
    
    prev_month_start = datetime.strptime(prev_month, "%Y-%m")
    if prev_month_start.month == 12:
        prev_month_end = datetime(prev_month_start.year + 1, 1, 1) - timedelta(days=1)
    else:
        prev_month_end = datetime(prev_month_start.year, prev_month_start.month + 1, 1) - timedelta(days=1)
    
    curr_total = df[(df[date_col] >= curr_month_start) & (df[date_col] <= curr_month_end)][metric_col].sum()
    prev_total = df[(df[date_col] >= prev_month_start) & (df[date_col] <= prev_month_end)][metric_col].sum()
    
    total_change = curr_total - prev_total
    total_change_pct = (curr_total - prev_total) / prev_total if prev_total > 0 else 0
    
    # Step 4: 拆解波动影响
    
    # 4.1 结构变动影响
    structure_impact = (
        (curr_workday_count_final * prev_workday_baseline_final +
         curr_nonworkday_count_final * prev_nonworkday_baseline_final) -
        (prev_workday_count_final * prev_workday_baseline_final +
         prev_nonworkday_count_final * prev_nonworkday_baseline_final)
    )
    
    # 4.2 趋势变动影响
    curr_month_days = (curr_month_end - curr_month_start).days + 1
    trend_impact = (
        curr_workday_count_final * (curr_workday_baseline_final - prev_workday_baseline_final) +
        curr_nonworkday_count_final * (curr_nonworkday_baseline_final - prev_nonworkday_baseline_final)
    ) / curr_month_days * curr_month_days
    
    # 4.3 各事件影响
    event_impacts: List[Dict] = []
    total_event_impact = 0.0
    
    for event in events_impact_info:
        if event["event_month"] == "current":
            impact = calculate_event_final_impact(
                df, date_col, metric_col, event["dates"],
                curr_workday_baseline_final, curr_nonworkday_baseline_final,
                curr_month_days, is_current_month=True
            ) * curr_month_days
        else:
            prev_month_days = (prev_month_end - prev_month_start).days + 1
            impact = calculate_event_final_impact(
                df, date_col, metric_col, event["dates"],
                curr_workday_baseline_final, curr_nonworkday_baseline_final,
                prev_month_days, is_current_month=False
            ) * prev_month_days
        
        event_impacts.append({
            "name": event["name"],
            "impact": impact,
            "impact_ratio": event["impact_ratio"],
            "event_month": event["event_month"],
        })
        total_event_impact += impact
    
    return {
        "current_month": current_month,
        "prev_month": prev_month,
        "curr_total": curr_total,
        "prev_total": prev_total,
        "total_change": total_change,
        "total_change_pct": total_change_pct,
        "structure_impact": structure_impact,
        "trend_impact": trend_impact,
        "event_impacts": event_impacts,
        "total_event_impact": total_event_impact,
        "baselines": {
            "curr_workday": curr_workday_baseline_final,
            "curr_nonworkday": curr_nonworkday_baseline_final,
            "prev_workday": prev_workday_baseline_final,
            "prev_nonworkday": prev_nonworkday_baseline_final,
        },
    }


def format_output(result: Dict) -> str:
    """格式化输出结果为表格"""
    lines = []
    total_change = result["total_change"]

    lines.append(f" {'影响因素':<8} {'绝对值':>8}  {'占比':>8}")

    # 总变动
    change_val = int(total_change)
    change_val_str = f"+{change_val}" if change_val >= 0 else str(change_val)
    lines.append(f" {'总变动':<8} {change_val_str:>8}  {'100.0%':>8}")

    # 结构变动
    structure_val = int(result["structure_impact"])
    structure_pct = result["structure_impact"] / total_change * 100 if total_change != 0 else 0
    structure_val_str = f"+{structure_val}" if structure_val >= 0 else str(structure_val)
    structure_pct_str = f"{structure_pct:.1f}%"
    lines.append(f" {'结构变动':<8} {structure_val_str:>8}  {structure_pct_str:>8}")

    # 趋势变动
    trend_val = int(result["trend_impact"])
    trend_pct = result["trend_impact"] / total_change * 100 if total_change != 0 else 0
    trend_val_str = f"+{trend_val}" if trend_val >= 0 else str(trend_val)
    trend_pct_str = f"{trend_pct:.1f}%"
    lines.append(f" {'趋势变动':<8} {trend_val_str:>8}  {trend_pct_str:>8}")

    # 事件影响（仅有事件时输出）
    if result["event_impacts"]:
        event_total_val = int(result["total_event_impact"])
        event_total_pct = result["total_event_impact"] / total_change * 100 if total_change != 0 else 0
        event_total_val_str = f"+{event_total_val}" if event_total_val >= 0 else str(event_total_val)
        event_total_pct_str = f"{event_total_pct:.1f}%"
        lines.append(f" {'事件影响':<8} {event_total_val_str:>8}  {event_total_pct_str:>8}")

        for event in result["event_impacts"]:
            event_val = int(event["impact"])
            event_pct = event["impact"] / total_change * 100 if total_change != 0 else 0
            event_val_str = f"+{event_val}" if event_val >= 0 else str(event_val)
            event_pct_str = f"{event_pct:.1f}%"
            lines.append(f"   {event['name']:<6} {event_val_str:>8}  {event_pct_str:>8}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="时间因素波动归因分析")
    parser.add_argument("--current-month", required=True, help="当前月，格式 YYYY-MM")
    parser.add_argument("--prev-month", required=True, help="上月，格式 YYYY-MM")
    parser.add_argument("--input-file", required=True, help="日粒度指标数据 CSV 文件")
    parser.add_argument("--date-col", default="date", help="日期列名，默认 date")
    parser.add_argument("--metric-col", required=True, help="指标列名")
    parser.add_argument("--events-file", default=None, help="事件信息 CSV 文件")
    parser.add_argument("--impact-threshold", type=float, default=0.10, help="事件影响度阈值，默认 0.10")
    parser.add_argument("--holiday-lead-days", type=int, default=1, help="节假日前置天数，默认 1")
    parser.add_argument("--event-lag-days", type=int, default=2, help="事件后置天数，默认 2")
    parser.add_argument("--output-file", default="", help="波动拆解结果输出路径")
    
    args = parser.parse_args()
    
    # 读取数据
    df = pd.read_csv(args.input_file)
    df[args.date_col] = pd.to_datetime(df[args.date_col])
    
    # 读取事件信息
    events_df = None
    if args.events_file:
        events_df = pd.read_csv(args.events_file)
    
    # 执行归因分析
    result = run_attribution(
        df=df,
        date_col=args.date_col,
        metric_col=args.metric_col,
        events_df=events_df,
        current_month=args.current_month,
        prev_month=args.prev_month,
        impact_threshold=args.impact_threshold,
        holiday_lead_days=args.holiday_lead_days,
        event_lag_days=args.event_lag_days,
    )
    
    # 输出结果
    output_text = format_output(result)
    print(output_text)

    if args.output_file:
        import json
        with open(args.output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n结果已保存到: {args.output_file}")


if __name__ == "__main__":
    main()

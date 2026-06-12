# -*- coding: utf-8 -*-
"""无监督聚类脚本；主结果写入 --output-json（分组 JSON），并 stdout 打印、stderr 输出相对路径。

支持：
- K-means (--method kmeans)
- 层次聚类 AgglomerativeClustering (--method hierarchical)
- DBSCAN (--method dbscan)

参数调优：加 --tune，按轮廓系数在网格/范围内择优（DBSCAN 仅在非噪声子集上计算轮廓系数）。

Usage:
    python clustering.py \\
        --input-file data.csv \\
        --id-col user_id \\
        --feature-cols 年龄 消费金额 访问次数 \\
        --method kmeans \\
        --n-clusters 5 \\
        --output-json clusters.json

    python clustering.py ... --method kmeans --tune --k-min 2 --k-max 10

    python clustering.py ... --method dbscan --tune \\
        --tune-eps 0.3,0.5,0.8,1.2 \\
        --tune-min-samples 3,5,10 \\
        --max-noise-ratio 0.35
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from json_groups import build_json_from_labels, write_print_json


METHOD_KMEANS = "kmeans"
METHOD_HIERARCHICAL = "hierarchical"
METHOD_DBSCAN = "dbscan"
METHODS = {METHOD_KMEANS, METHOD_HIERARCHICAL, METHOD_DBSCAN}

LINKAGES = ("ward", "complete", "average", "single")


def _parse_csv_nums(s: str) -> List[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def _parse_csv_ints(s: str) -> List[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _build_scaler(name: str):
    name = (name or "standard").lower()
    if name in ("standard", "zscore", "z"):
        return StandardScaler()
    if name in ("minmax", "min-max", "mm"):
        return MinMaxScaler()
    if name == "none" or name == "off":
        return None
    raise ValueError(f"Unknown scaler: {name}")


def _prepare_features(
    df: pd.DataFrame,
    feature_cols: Sequence[str],
    drop_na: bool,
    fill_mean: bool,
) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """返回 (用于对齐的 df 子集, 有效行索引在原 df 中的位置, 特征矩阵 X)。"""
    miss = [c for c in feature_cols if c not in df.columns]
    if miss:
        raise ValueError(f"Missing columns in CSV: {miss}")

    sub = df[feature_cols].apply(pd.to_numeric, errors="coerce")
    if fill_mean:
        filled = sub.copy()
        for c in feature_cols:
            m = filled[c].mean()
            filled[c] = filled[c].fillna(m)
        X = filled.to_numpy(dtype=float)
        idx = np.arange(len(df))
        return df.reset_index(drop=True), idx, X
    if drop_na:
        valid = sub.notna().all(axis=1)
        idx = np.where(valid.to_numpy())[0]
        X = sub.iloc[idx].to_numpy(dtype=float)
        return df.iloc[idx].reset_index(drop=True), idx, X
    if sub.isna().any().any():
        raise ValueError("Feature matrix contains NaN. Use default drop (NaN rows), --skip-drop-na with --fill-mean, or clean data.")
    X = sub.to_numpy(dtype=float)
    idx = np.arange(len(df))
    return df.reset_index(drop=True), idx, X


def _scale_X(X: np.ndarray, scaler) -> np.ndarray:
    if scaler is None:
        return X
    return scaler.fit_transform(X)


def _silhouette_or_nan(X: np.ndarray, labels: np.ndarray) -> float:
    uniq = np.unique(labels)
    if len(uniq) < 2 or len(labels) < 3:
        return float("nan")
    # 所有样本同一簇等边缘情况
    try:
        return float(silhouette_score(X, labels))
    except Exception:
        return float("nan")


def _silhouette_dbscan(X: np.ndarray, labels: np.ndarray) -> float:
    """仅在非噪声点上计算轮廓系数。"""
    mask = labels >= 0
    if mask.sum() < 3:
        return float("nan")
    labs = labels[mask]
    uniq = np.unique(labs)
    if len(uniq) < 2:
        return float("nan")
    try:
        return float(silhouette_score(X[mask], labs))
    except Exception:
        return float("nan")


def _noise_ratio(labels: np.ndarray) -> float:
    n = len(labels)
    if n == 0:
        return 1.0
    return float(np.sum(labels < 0) / n)


def run_kmeans(
    X: np.ndarray,
    n_clusters: int,
    random_state: int,
    n_init: int,
) -> Tuple[np.ndarray, np.ndarray]:
    km = KMeans(
        n_clusters=n_clusters,
        n_init=n_init,
        random_state=random_state,
        max_iter=300,
    )
    labels = km.fit_predict(X)
    return labels, km.cluster_centers_


def run_hierarchical(
    X: np.ndarray,
    n_clusters: int,
    linkage: str,
) -> np.ndarray:
    if X.shape[0] < n_clusters:
        raise ValueError("n_samples must be >= n_clusters")
    if linkage == "ward":
        ac = AgglomerativeClustering(n_clusters=n_clusters, linkage="ward")
    else:
        ac = AgglomerativeClustering(
            n_clusters=n_clusters,
            linkage=linkage,
            metric="euclidean",
        )
    return ac.fit_predict(X)


def run_dbscan(X: np.ndarray, eps: float, min_samples: int) -> np.ndarray:
    db = DBSCAN(eps=eps, min_samples=min_samples)
    return db.fit_predict(X)


def tune_kmeans(
    X: np.ndarray,
    k_min: int,
    k_max: int,
    random_state: int,
    n_init: int,
) -> Tuple[int, float, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    best_k, best_score = None, float("-inf")
    n = len(X)
    for k in range(max(2, k_min), min(k_max, n - 1) + 1):
        if k >= n:
            continue
        labels, _ = run_kmeans(X, k, random_state, n_init)
        score = _silhouette_or_nan(X, labels)
        rows.append({"n_clusters": k, "silhouette": score})
        if not np.isnan(score) and score > best_score:
            best_score = score
            best_k = k
    if best_k is None:
        raise ValueError("K-means tuning failed: no valid k in range (check sample size).")
    return best_k, best_score, rows


def tune_hierarchical(
    X: np.ndarray,
    k_min: int,
    k_max: int,
    linkages: Sequence[str],
) -> Tuple[int, str, float, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    best_k, best_link, best_score = None, None, float("-inf")
    n = len(X)
    for linkage in linkages:
        if linkage == "ward" and X.shape[1] < 1:
            continue
        for k in range(max(2, k_min), min(k_max, n - 1) + 1):
            if k >= n:
                continue
            try:
                labels = run_hierarchical(X, k, linkage)
            except Exception as e:
                rows.append({"n_clusters": k, "linkage": linkage, "silhouette": None, "error": str(e)})
                continue
            score = _silhouette_or_nan(X, labels)
            rows.append({"n_clusters": k, "linkage": linkage, "silhouette": score})
            if not np.isnan(score) and score > best_score:
                best_score = score
                best_k, best_link = k, linkage
    if best_k is None or best_link is None:
        raise ValueError("Hierarchical tuning failed: no valid configuration.")
    return best_k, best_link, best_score, rows


def tune_dbscan(
    X: np.ndarray,
    eps_list: Sequence[float],
    min_samples_list: Sequence[int],
    max_noise_ratio: float,
) -> Tuple[float, int, float, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    best_eps, best_ms, best_score = None, None, float("-inf")
    for eps in eps_list:
        for ms in min_samples_list:
            labels = run_dbscan(X, float(eps), int(ms))
            nr = _noise_ratio(labels)
            n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
            score = _silhouette_dbscan(X, labels)
            row: Dict[str, Any] = {
                "eps": eps,
                "min_samples": ms,
                "n_clusters_est": n_clusters,
                "noise_ratio": nr,
                "silhouette_non_noise": score,
            }
            if nr > max_noise_ratio or n_clusters < 2 or np.isnan(score):
                row["eligible"] = False
            else:
                row["eligible"] = True
                if score > best_score:
                    best_score = score
                    best_eps, best_ms = float(eps), int(ms)
            rows.append(row)
    if best_eps is None:
        raise ValueError(
            "DBSCAN tuning failed: no (eps, min_samples) met n_clusters>=2, "
            f"noise_ratio<={max_noise_ratio}, and valid silhouette. "
            "Try widening --tune-eps / --tune-min-samples or increasing --max-noise-ratio."
        )
    return best_eps, best_ms, best_score, rows


def run_pipeline(args: argparse.Namespace) -> pd.DataFrame:
    df = pd.read_csv(args.input_file)
    if args.id_col not in df.columns:
        raise ValueError(f"id column not found: {args.id_col}")

    aligned_df, _, X = _prepare_features(
        df,
        args.feature_cols,
        drop_na=args.drop_na_rows,
        fill_mean=args.fill_mean,
    )
    # id 与 aligned_df 对齐：prepare 可能删行
    ids = aligned_df[args.id_col]

    scaler = _build_scaler(args.scale)
    Xs = _scale_X(X, scaler)

    tuning_report: Optional[Dict[str, Any]] = None
    centroids: Optional[np.ndarray] = None

    method = args.method.lower()
    if method == METHOD_KMEANS:
        if args.tune:
            best_k, best_s, grid = tune_kmeans(
                Xs, args.k_min, args.k_max, args.random_state, args.n_init
            )
            tuning_report = {"method": METHOD_KMEANS, "best_n_clusters": best_k, "best_silhouette": best_s, "grid": grid}
            labels, centroids = run_kmeans(Xs, best_k, args.random_state, args.n_init)
        else:
            if args.n_clusters is None:
                raise ValueError("K-means requires --n-clusters or --tune")
            labels, centroids = run_kmeans(Xs, args.n_clusters, args.random_state, args.n_init)

    elif method == METHOD_HIERARCHICAL:
        linkage = args.linkage
        if args.tune:
            links = args.tune_linkages or [args.linkage]
            best_k, best_link, best_s, grid = tune_hierarchical(Xs, args.k_min, args.k_max, links)
            tuning_report = {
                "method": METHOD_HIERARCHICAL,
                "best_n_clusters": best_k,
                "best_linkage": best_link,
                "best_silhouette": best_s,
                "grid": grid,
            }
            labels = run_hierarchical(Xs, best_k, best_link)
            linkage = best_link
        else:
            if args.n_clusters is None:
                raise ValueError("Hierarchical clustering requires --n-clusters or --tune")
            labels = run_hierarchical(Xs, args.n_clusters, linkage)

    elif method == METHOD_DBSCAN:
        if args.tune:
            eps_list = args.tune_eps or [args.eps]
            ms_list = args.tune_min_samples or [args.min_samples]
            best_eps, best_ms, best_s, grid = tune_dbscan(Xs, eps_list, ms_list, args.max_noise_ratio)
            tuning_report = {
                "method": METHOD_DBSCAN,
                "best_eps": best_eps,
                "best_min_samples": best_ms,
                "best_silhouette_non_noise": best_s,
                "grid": grid,
            }
            labels = run_dbscan(Xs, best_eps, best_ms)
        else:
            if args.eps is None or args.min_samples is None:
                raise ValueError("DBSCAN requires --eps and --min-samples, or --tune with grids")
            labels = run_dbscan(Xs, float(args.eps), int(args.min_samples))

    else:
        raise ValueError(f"Unknown method: {method}")

    out = pd.DataFrame(
        {
            args.id_col: ids.values,
            "cluster_label": labels,
            "is_noise": labels < 0,
        }
    )

    if args.tuning_report_file and tuning_report is not None:
        with open(args.tuning_report_file, "w", encoding="utf-8") as f:
            json.dump(tuning_report, f, ensure_ascii=False, indent=2)

    # 质心表（可选）
    if centroids is not None and args.centroids_file:
        cen_df = pd.DataFrame(centroids, columns=args.feature_cols)
        cen_df.insert(0, "cluster_label", range(len(cen_df)))
        cen_df.to_csv(args.centroids_file, index=False)

    return out


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Clustering with optional hyperparameter tuning.")
    p.add_argument("--input-file", required=True, help="Input CSV path")
    p.add_argument("--id-col", required=True, help="Row id column name")
    p.add_argument(
        "--feature-cols",
        nargs="+",
        required=True,
        help="Numeric feature column names",
    )
    p.add_argument(
        "--method",
        required=True,
        choices=sorted(METHODS),
        help="kmeans | hierarchical | dbscan",
    )
    p.add_argument(
        "--scale",
        default="standard",
        help="Feature scaling: standard | minmax | none (default: standard)",
    )
    p.add_argument("--output-json", required=True, help="Output JSON: cluster 1..K -> ids; DBSCAN noise under \"noise\"")
    p.add_argument("--random-state", type=int, default=42, help="KMeans random seed")
    p.add_argument("--n-init", type=int, default=10, help="KMeans n_init")

    p.add_argument("--n-clusters", type=int, default=None, help="K for kmeans / hierarchical")
    p.add_argument(
        "--linkage",
        default="ward",
        choices=list(LINKAGES),
        help="Agglomerative linkage (default: ward)",
    )

    p.add_argument("--eps", type=float, default=None, help="DBSCAN eps")
    p.add_argument("--min-samples", type=int, default=None, help="DBSCAN min_samples")

    p.add_argument(
        "--skip-drop-na",
        action="store_false",
        dest="drop_na_rows",
        help="Do not drop rows with NaN (then use --fill-mean or ensure no NaN)",
    )
    p.add_argument("--fill-mean", action="store_true", help="Impute feature NaN with column mean")
    p.set_defaults(drop_na_rows=True)
    p.add_argument(
        "--centroids-file",
        default=None,
        help="If set and method is kmeans, write cluster centroids CSV (scaled space)",
    )

    tune = p.add_argument_group("tuning")
    tune.add_argument(
        "--tune",
        action="store_true",
        help="Grid search: maximize silhouette (DBSCAN: on non-noise points, with noise cap)",
    )
    tune.add_argument("--k-min", type=int, default=2, help="Min clusters for kmeans / hierarchical tune")
    tune.add_argument("--k-max", type=int, default=10, help="Max clusters for kmeans / hierarchical tune")
    tune.add_argument(
        "--tune-linkages",
        nargs="+",
        choices=list(LINKAGES),
        default=None,
        help="Hierarchical: linkages to try when --tune",
    )
    tune.add_argument(
        "--tune-eps",
        type=str,
        default=None,
        help='DBSCAN: comma-separated eps, e.g. "0.3,0.5,0.8"',
    )
    tune.add_argument(
        "--tune-min-samples",
        type=str,
        default=None,
        help='DBSCAN: comma-separated min_samples, e.g. "3,5,10"',
    )
    tune.add_argument(
        "--max-noise-ratio",
        type=float,
        default=0.35,
        help="DBSCAN tune: discard trials with noise ratio above this (default: 0.35)",
    )
    tune.add_argument(
        "--tuning-report-file",
        default=None,
        help="Write JSON with grid results and chosen hyperparameters",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_argparser().parse_args(list(argv) if argv is not None else None)

    # 解析 DBSCAN 调优网格
    args.tune_eps = _parse_csv_nums(args.tune_eps) if args.tune_eps else None
    args.tune_min_samples = _parse_csv_ints(args.tune_min_samples) if args.tune_min_samples else None

    if args.tune and args.method == METHOD_DBSCAN:
        if not args.tune_eps or not args.tune_min_samples:
            raise SystemExit("DBSCAN --tune requires --tune-eps and --tune-min-samples")

    try:
        out_df = run_pipeline(args)
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 1

    payload = build_json_from_labels(
        out_df[args.id_col].values,
        out_df["cluster_label"].values,
    )
    write_print_json(args.output_json, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

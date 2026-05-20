from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def run_attribution(
    df: pd.DataFrame,
    dimension_col: str,
    current_col: str,
    previous_col: str,
) -> pd.DataFrame:
    work = df.copy()
    work["delta"] = work[current_col] - work[previous_col]
    denom = work["delta"].abs().sum()
    if denom == 0:
        work["contribution_share"] = 0.0
    else:
        work["contribution_share"] = work["delta"] / denom
    return work.sort_values("delta", ascending=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple BI attribution analysis")
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--dimension-col", required=True)
    parser.add_argument("--current-col", required=True)
    parser.add_argument("--previous-col", required=True)
    parser.add_argument("--output-file", default="")
    args = parser.parse_args()

    df = pd.read_csv(args.input_file)
    result = run_attribution(
        df,
        args.dimension_col,
        args.current_col,
        args.previous_col,
    )
    if args.output_file:
        Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(args.output_file, index=False)
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()


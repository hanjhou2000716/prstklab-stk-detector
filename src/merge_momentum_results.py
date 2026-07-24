"""Merge segmented Taiwan momentum CSV artifacts into one ranked result."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd

def merge_results(directory: Path) -> pd.DataFrame:
    files = list(directory.rglob("taiwan-momentum-scan-*.csv"))
    frames = []
    for path in files:
        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            continue
        if "score" in frame.columns and not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("score", ascending=False).head(10).reset_index(drop=True)

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("directory"); parser.add_argument("--output", default="data/taiwan-momentum-combined.csv")
    args = parser.parse_args(); result = merge_results(Path(args.directory)); output = Path(args.output); output.parent.mkdir(exist_ok=True); result.to_csv(output, index=False, encoding="utf-8-sig")
    output.with_suffix(".json").write_text(json.dumps({"candidates": len(result)}, ensure_ascii=False), encoding="utf-8")
if __name__ == "__main__": main()

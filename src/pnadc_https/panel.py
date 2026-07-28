"""Deterministic construction of five-wave PNADC person panels."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from .utils import atomic_json, portable_path


HOUSEHOLD_COLUMNS = ("upa", "v1008")
SIGNATURE_COLUMNS = ("v2007", "v2008", "v20081", "v20082")


def build_panel(
    inputs: Sequence[str | Path],
    output: str | Path,
    panel_id: str,
    wide: bool = False,
    force: bool = False,
) -> dict[str, object]:
    """Build a panel from 2-5 consecutive quarterly Parquet files.

    Wave ``n`` retains records where ``v1016 == n``. Individuals are linked
    within dwelling by sex and reported birth date; duplicate signatures
    (for example twins) receive a stable rank based on ``v2003``.
    """
    if not 2 <= len(inputs) <= 5:
        raise ValueError("Panel construction requires 2 to 5 consecutive quarterly files")
    target = Path(output).resolve()
    if target.exists() and not force:
        raise FileExistsError(f"Output already exists; pass --force to replace it: {target}")
    try:
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Panel construction requires pandas and pyarrow") from exc

    frames = []
    required = set(HOUSEHOLD_COLUMNS + SIGNATURE_COLUMNS + ("v2003",))
    for wave, raw_path in enumerate(inputs, start=1):
        path = Path(raw_path).resolve()
        frame = pq.read_table(path).to_pandas()
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{path.name} lacks panel identification columns: {', '.join(missing)}")
        if "v1016" not in frame.columns:
            # v1016 identifies which visit a record belongs to, and the wave
            # filter is the whole basis of the linkage. Inventing it would
            # quietly treat an unsuitable input — a column-projected file, or
            # quarters given out of order — as if it were the right one.
            raise ValueError(
                f"{path.name} has no v1016 column, so its visit number is unknown; "
                "convert without --columns, or include v1016 in the selection"
            )
        frame = frame.loc[frame["v1016"] == wave].copy()
        if frame.empty:
            raise ValueError(
                f"{path.name} contains no records for visit {wave}; "
                "inputs must be consecutive quarters in chronological order, "
                "beginning with the panel's first visit"
            )
        frame["panel_wave"] = wave
        frames.append(frame)

    long = pd.concat(frames, ignore_index=True, sort=False)
    long["panel_id"] = str(panel_id)
    household_keys = long[list(HOUSEHOLD_COLUMNS)].astype("string").fillna("")
    household_keys.insert(0, "panel_id", str(panel_id))
    long["household_id"] = pd.util.hash_pandas_object(household_keys, index=False).map(lambda value: f"{value:016x}")
    signature_group = list(HOUSEHOLD_COLUMNS + SIGNATURE_COLUMNS + ("panel_wave",))
    long = long.sort_values(signature_group + ["v2003"], kind="stable")
    long["signature_rank"] = long.groupby(signature_group, dropna=False).cumcount() + 1
    person_keys = long[["household_id", *SIGNATURE_COLUMNS, "signature_rank"]].astype("string").fillna("")
    person_keys.insert(0, "panel_id", str(panel_id))
    long["person_id"] = pd.util.hash_pandas_object(person_keys, index=False).map(lambda value: f"{value:016x}")
    long = long.sort_values(["household_id", "person_id", "panel_wave"], kind="stable")

    if wide:
        identifiers = ["panel_id", "household_id", "person_id"]
        value_columns = [column for column in long.columns if column not in identifiers + ["panel_wave"]]
        table_frame = long.set_index(identifiers + ["panel_wave"])[value_columns].unstack("panel_wave")
        table_frame.columns = [f"{name}_{wave}" for name, wave in table_frame.columns]
        table_frame = table_frame.reset_index()
    else:
        table_frame = long

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    pq.write_table(pa.Table.from_pandas(table_frame, preserve_index=False), temporary, compression="zstd")
    os.replace(temporary, target)
    result: dict[str, object] = {
        "schema_version": 2,
        "panel_id": str(panel_id),
        # Recorded relative to the panel's own directory where possible, so the
        # record stays meaningful if the outputs are moved together, matching
        # the conversion provenance.
        "paths_relative_to": "the output directory",
        "inputs": [portable_path(Path(path).resolve(), target.parent) for path in inputs],
        "output": target.name,
        "wide": wide,
        "rows": len(table_frame),
        "persons": int(long["person_id"].nunique()),
        "method": "dwelling + sex + birth date + within-wave duplicate rank",
    }
    atomic_json(target.with_suffix(target.suffix + ".provenance.json"), result)
    return result

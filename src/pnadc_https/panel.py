"""Deterministic construction of five-wave PNADC person panels."""

from __future__ import annotations

import os
import re
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
    panel_match = re.fullmatch(r"(20\d{2})([1-4])", str(panel_id))
    if panel_match is None:
        raise ValueError(
            "panel_id must be the first-wave period as YYYYQ, for example 20241"
        )
    first_period = int(panel_match.group(1)) * 4 + int(panel_match.group(2)) - 1
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
    required = set(
        HOUSEHOLD_COLUMNS
        + SIGNATURE_COLUMNS
        + ("ano", "trimestre", "v1016", "v2003")
    )
    for wave, raw_path in enumerate(inputs, start=1):
        path = Path(raw_path).resolve()
        frame = pq.read_table(path).to_pandas()
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{path.name} lacks panel identification columns: {', '.join(missing)}")
        period_rows = frame[["ano", "trimestre"]].dropna().drop_duplicates()
        if len(period_rows) != 1:
            raise ValueError(
                f"{path.name} must contain exactly one ano/trimestre period; "
                f"found {len(period_rows)}"
            )
        year = int(period_rows.iloc[0]["ano"])
        quarter = int(period_rows.iloc[0]["trimestre"])
        if quarter not in (1, 2, 3, 4):
            raise ValueError(f"{path.name} has invalid trimestre {quarter!r}")
        actual_period = year * 4 + quarter - 1
        expected_period = first_period + wave - 1
        if actual_period != expected_period:
            expected_year, expected_offset = divmod(expected_period, 4)
            raise ValueError(
                f"{path.name} is {year}Q{quarter}; expected "
                f"{expected_year}Q{expected_offset + 1}. Inputs must be "
                "consecutive quarters in chronological order"
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

from __future__ import annotations

import io
from pathlib import Path


def profile_dataframe(df) -> dict:
    """Analyse a DataFrame and return a plain-dict profile of issues found."""
    import pandas as pd

    issues = []
    total_rows = len(df)
    total_cols = len(df.columns)

    null_counts = df.isnull().sum()
    null_cols = {col: int(cnt) for col, cnt in null_counts.items() if cnt > 0}
    if null_cols:
        issues.append(f"{sum(null_cols.values())} null values across {len(null_cols)} column(s): {', '.join(null_cols)}")

    dup_rows = int(df.duplicated().sum())
    if dup_rows:
        issues.append(f"{dup_rows} duplicate row(s)")

    whitespace_cols = []
    for col in df.select_dtypes(include="object").columns:
        if df[col].astype(str).str.strip().ne(df[col].astype(str)).any():
            whitespace_cols.append(col)
    if whitespace_cols:
        issues.append(f"Leading/trailing whitespace in: {', '.join(whitespace_cols)}")

    mixed_cols = []
    for col in df.columns:
        if df[col].dtype == object:
            non_null = df[col].dropna()
            types = set(type(v).__name__ for v in non_null)
            if len(types) > 1:
                mixed_cols.append(col)
    if mixed_cols:
        issues.append(f"Mixed data types in: {', '.join(mixed_cols)}")

    return {
        "rows": total_rows,
        "columns": total_cols,
        "column_names": list(df.columns),
        "null_cols": null_cols,
        "duplicate_rows": dup_rows,
        "whitespace_cols": whitespace_cols,
        "issues": issues,
        "issue_count": len(issues),
    }


def clean_dataframe(df):
    """Apply standard cleaning operations and return cleaned DataFrame."""
    # Strip whitespace from string columns
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    # Drop fully empty rows/columns
    df = df.dropna(how="all")
    df = df.loc[:, df.columns.str.strip() != ""]

    # Remove duplicate rows
    df = df.drop_duplicates()

    # Reset index
    df = df.reset_index(drop=True)

    return df


def generate_cleaning_script(filename: str, profile: dict) -> str:
    """Generate a reusable Python cleaning script based on the profile."""
    ext = Path(filename).suffix.lower()
    reader = "pd.read_csv('input_file.csv')" if ext == ".csv" else f"pd.read_excel('input_file{ext}')"

    steps = ["import pandas as pd", "", f"df = {reader}", ""]

    if profile.get("whitespace_cols"):
        steps += [
            "# Strip whitespace from text columns",
            "for col in df.select_dtypes(include='object').columns:",
            "    df[col] = df[col].str.strip()",
            "",
        ]

    if profile.get("null_cols"):
        steps += [
            "# Drop fully empty rows",
            "df = df.dropna(how='all')",
            "",
        ]

    if profile.get("duplicate_rows", 0) > 0:
        steps += [
            "# Remove duplicate rows",
            "df = df.drop_duplicates()",
            "",
        ]

    steps += [
        "# Reset index after cleaning",
        "df = df.reset_index(drop=True)",
        "",
        "# Save cleaned file",
        "df.to_csv('cleaned_output.csv', index=False)",
        "print(f'Done — {len(df)} rows remaining')",
    ]

    return "\n".join(steps)


def parse_upload(data: bytes, filename: str):
    """Read uploaded bytes into a DataFrame. Supports CSV, XLS, XLSX, JSON."""
    import pandas as pd

    ext = Path(filename).suffix.lower()
    buf = io.BytesIO(data)

    if ext == ".csv":
        return pd.read_csv(buf)
    elif ext in (".xlsx", ".xls"):
        return pd.read_excel(buf, engine="openpyxl" if ext == ".xlsx" else "xlrd")
    elif ext == ".json":
        return pd.read_json(buf)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def dataframe_to_bytes(df, filename: str) -> tuple[bytes, str]:
    """Serialise a cleaned DataFrame back to bytes. Returns (bytes, media_type)."""
    ext = Path(filename).suffix.lower()
    buf = io.BytesIO()
    if ext == ".csv":
        df.to_csv(buf, index=False)
        return buf.getvalue(), "text/csv"
    elif ext in (".xlsx", ".xls"):
        df.to_excel(buf, index=False, engine="openpyxl")
        return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        df.to_csv(buf, index=False)
        return buf.getvalue(), "text/csv"

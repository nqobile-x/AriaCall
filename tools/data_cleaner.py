"""Type-aware CSV/Excel/JSON cleaner with an auditable change report.

Design notes
- Everything is read as text first so nothing (phone numbers, ids, zip codes) is
  silently coerced by pandas before we decide what the column actually is.
- Each column is classified (id, email, phone, date, number, category, text) and
  cleaned by rules for that type.
- Values that cannot be repaired are blanked, never guessed, and every change is
  logged with its original value so the result can be audited or reversed.
- Defaults assume South African data (+27 phone numbers, day-first dates,
  SA provinces). Other countries' "+" numbers are kept as-is.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

MAX_LOGGED_CHANGES = 500
DEFAULT_COUNTRY_CODE = "27"

# Reason labels (double as the human-readable issue/change descriptions).
R_WS = "Extra whitespace"
R_MISSING = "Placeholder missing values (N/A, NULL, -, Unknown)"
R_CASE = "Inconsistent capitalisation"
R_CATEGORY = "Inconsistent spellings (e.g. GP / Gauteng, F / Female)"
R_DATE = "Dates in mixed formats"
R_DATE_BAD = "Unreadable dates (blanked)"
R_EMAIL = "Invalid or placeholder email addresses (blanked)"
R_PHONE = "Phone numbers in mixed formats"
R_PHONE_BAD = "Invalid or placeholder phone numbers (blanked)"
R_NUM_FMT = "Numbers with currency symbols or separators"
R_NUM_BAD = "Non-numeric values in a numeric column (blanked)"
R_RANGE = "Out-of-range values (blanked)"
R_FORMULA = "Text that spreadsheets would run as a formula (neutralised)"
R_DUP = "Duplicate records (removed)"

_NULL_TOKENS = {"", "n/a", "na", "nan", "null", "nil", "-", "--", "?", "unknown", "undefined", "#n/a", "missing"}
_WS = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"^[a-z0-9._%+\-']+@[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}$")
_PLACEHOLDER_EMAILS = {"unknown@unknown.com", "test@test.com", "none@none.com", "noemail@noemail.com", "na@na.com", "a@a.com"}
_PLAIN_NUM = re.compile(r"^[+-]?\d+(\.\d+)?$")
_DMY = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$")
_YMD = re.compile(r"^(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})$")
_ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d")
_TEXT_DATE_FORMATS = ("%B %d %Y", "%b %d %Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%d %B, %Y", "%d-%b-%Y")
_NAME_PARTICLES = {"van", "der", "de", "den", "du", "von", "la", "le", "ten", "ter", "da", "di", "del", "bin", "al", "des"}

_PHONE_TOKENS = {"phone", "mobile", "cell", "tel", "telephone", "msisdn", "whatsapp"}
_DATE_TOKENS = {"date", "dob", "birthday", "login", "timestamp", "created", "updated", "datetime", "at"}
_NUMERIC_HINT_TOKENS = {"age", "count", "qty", "quantity", "score", "year", "years", "rating", "amount", "price", "total", "spend", "cost", "salary", "fee", "revenue"}
_MONEY_TOKENS = {"spend", "price", "amount", "cost", "total", "revenue", "salary", "fee"}

_GENDERS = {
    "m": "Male", "male": "Male", "man": "Male", "boy": "Male",
    "f": "Female", "female": "Female", "woman": "Female", "girl": "Female",
    "nb": "Non-binary", "non-binary": "Non-binary", "nonbinary": "Non-binary", "other": "Other",
}
_SA_PROVINCES = {
    "gauteng": "Gauteng", "gp": "Gauteng",
    "westerncape": "Western Cape", "wc": "Western Cape",
    "easterncape": "Eastern Cape", "ec": "Eastern Cape",
    "northerncape": "Northern Cape", "nc": "Northern Cape",
    "freestate": "Free State", "fs": "Free State",
    "limpopo": "Limpopo", "lp": "Limpopo",
    "mpumalanga": "Mpumalanga", "mp": "Mpumalanga",
    "northwest": "North West", "nw": "North West",
    "kwazulunatal": "KwaZulu-Natal", "kzn": "KwaZulu-Natal", "kwazulu": "KwaZulu-Natal", "natal": "KwaZulu-Natal",
}


# ── change recording ──────────────────────────────────────────────────────────

class _Recorder:
    def __init__(self) -> None:
        self.counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.changes: list[dict] = []

    def log(self, idx: int, col: str, before, after, reason: str) -> None:
        self.counts[reason][col] += 1
        if len(self.changes) < MAX_LOGGED_CHANGES:
            self.changes.append({"row": idx + 2, "column": col, "before": before, "after": after, "reason": reason})

    def summary(self) -> list[dict]:
        rows = [{"reason": r, "count": sum(c.values()), "columns": sorted(c)} for r, c in self.counts.items()]
        return sorted(rows, key=lambda r: -r["count"])


# ── small parsers ─────────────────────────────────────────────────────────────

def _is_na(value) -> bool:
    if value is None:
        return True
    try:
        return bool(value != value)  # NaN
    except TypeError:
        return type(value).__name__ == "NAType"  # pd.NA has no truth value


def _tokens(name: str) -> set[str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name))
    return set(re.findall(r"[a-z]+", spaced.lower()))


def _to_number(text: str):
    """Return (value, was_plain) or None when the text is not a number."""
    t = text.replace(" ", " ").strip()
    t = re.sub(r"^(zar|usd|eur|gbp|[R$€£])\s*", "", t, flags=re.I).replace(" ", "")
    plain = bool(_PLAIN_NUM.match(t))
    if not plain:
        if re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?", t):
            t = t.replace(",", "")
        elif re.fullmatch(r"[+-]?\d+,\d{1,2}", t):
            t = t.replace(",", ".")
        else:
            return None
    try:
        return float(t), plain and t == text.strip()
    except ValueError:
        return None


def _safe_dt(year: int, month: int, day: int):
    if not 1900 <= year <= 2100:
        return None
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _parse_date(text: str, dayfirst: bool):
    m = _YMD.match(text)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        return _safe_dt(y, mo, d)
    m = _DMY.match(text)
    if m:
        a, b, y = (int(g) for g in m.groups())
        day, month = (a, b) if dayfirst else (b, a)
        return _safe_dt(y, month, day) or _safe_dt(y, day, month)
    if _ISO_TIME.match(text):
        try:
            dt = datetime.fromisoformat(text.replace("Z", ""))
            return dt.replace(tzinfo=None) if 1900 <= dt.year <= 2100 else None
        except ValueError:
            return None
    for fmt in _TEXT_DATE_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            return dt if 1900 <= dt.year <= 2100 else None
        except ValueError:
            continue
    return None


def _dayfirst_for(values: list[str]) -> tuple[bool, int]:
    """Decide dd/mm vs mm/dd for a column. Returns (dayfirst, ambiguous_count)."""
    day_evidence = month_evidence = ambiguous = 0
    for v in values:
        m = _DMY.match(v)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12:
            day_evidence += 1
        elif b > 12:
            month_evidence += 1
        elif a != b:
            ambiguous += 1
    return month_evidence <= day_evidence, ambiguous


def _cap_word(word: str) -> str:
    return "-".join("'".join(p[:1].upper() + p[1:] for p in hyphen.split("'")) for hyphen in word.split("-"))


def _smart_title(text: str) -> str:
    out = []
    for i, word in enumerate(text.split(" ")):
        lower = word.lower()
        out.append(lower if i > 0 and lower in _NAME_PARTICLES else _cap_word(lower))
    return " ".join(out)


def _is_mono(text: str) -> bool:
    return any(c.isalpha() for c in text) and (text.islower() or text.isupper())


def _clean_phone(text: str, country_code: str = DEFAULT_COUNTRY_CODE):
    digits = re.sub(r"[^\d+]", "", text)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    bare = digits.lstrip("+")
    if not bare or len(set(bare)) == 1:
        return None  # 0000000000 / 1111111111 placeholders
    if digits.startswith("+" + country_code) and len(bare) == len(country_code) + 9:
        return "+" + bare
    if bare.startswith(country_code) and len(bare) == len(country_code) + 9 and not digits.startswith("+"):
        return "+" + bare
    if digits.startswith("0") and len(digits) == 10:
        return "+" + country_code + digits[1:]
    if digits.startswith("+") and 8 <= len(bare) <= 15:
        return "+" + bare
    return None


# ── loading ───────────────────────────────────────────────────────────────────

def _to_text_frame(df):
    """Every cell becomes str or None; column names become unique stripped strings."""
    import pandas as pd

    names: list[str] = []
    seen: Counter = Counter()
    for c in df.columns:
        base = str(c).strip()
        seen[base] += 1
        names.append(base if seen[base] == 1 else f"{base}.{seen[base] - 1}")
    data = {n: [None if _is_na(v) else str(v) for v in df.iloc[:, i]] for i, n in enumerate(names)}
    return pd.DataFrame(data, columns=names, dtype=object)


def _strip_and_null(series, col: str, rec: _Recorder):
    out = []
    for idx, v in series.items():
        if _is_na(v):
            out.append(None)
            continue
        stripped = v.strip()
        if stripped.lower() in _NULL_TOKENS:
            if stripped != "":
                rec.log(idx, col, v, None, R_MISSING)
            elif v != "":
                rec.log(idx, col, v, None, R_MISSING)
            out.append(None)
            continue
        if stripped != v:
            rec.log(idx, col, v, stripped, R_WS)
        out.append(stripped)
    return out


# ── column classification ─────────────────────────────────────────────────────

def _ratio(values: list[str], predicate) -> float:
    return sum(1 for v in values if predicate(v)) / len(values) if values else 0.0


def _classify(col: str, values: list[str]) -> str:
    toks = _tokens(col)
    if not values:
        return "empty"
    if toks & {"id", "uuid", "guid"}:
        return "id"
    if toks & {"email", "mail"} or _ratio(values, lambda v: "@" in v) >= 0.8:
        return "email"
    if toks & _PHONE_TOKENS:
        return "phone"
    if toks & {"gender", "sex"}:
        return "gender"
    dayfirst, _ = _dayfirst_for(values)
    date_ratio = _ratio(values, lambda v: _parse_date(v, dayfirst) is not None)
    if date_ratio >= (0.6 if toks & _DATE_TOKENS else 0.8):
        return "date"
    number_threshold = 0.5 if toks & _NUMERIC_HINT_TOKENS else 0.8
    if not any(re.fullmatch(r"0\d+", v) for v in values) and _ratio(values, lambda v: _to_number(v) is not None) >= number_threshold:
        return "number"
    if toks & {"province", "state"}:
        return "province"
    words = max(len(v.split()) for v in values)
    avg_len = sum(len(v) for v in values) / len(values)
    return "short_text" if avg_len <= 40 and words <= 6 else "free_text"


def _display_kind(kind: str, values: list[str]) -> str:
    if kind == "number":
        parsed = [_to_number(v) for v in values]
        return "integer" if all(p and p[0].is_integer() and "." not in v for p, v in zip(parsed, values) if p) else "decimal"
    if kind in ("gender", "province"):
        return "category"
    if kind == "short_text":
        return "category" if len(set(values)) <= max(10, len(values) * 0.2) else "text"
    return "text" if kind == "free_text" else kind


# ── per-kind cleaners (each returns a new list aligned with `series.index`) ──

def _neutralise_formula(idx: int, col: str, v: str, rec: _Recorder) -> str:
    risky = v[0] in "=@" or (v[0] in "+-" and len(v) > 1 and not (v[1].isdigit() or v[1] in ". "))
    if risky:
        rec.log(idx, col, v, "'" + v, R_FORMULA)
        return "'" + v
    return v


def _clean_email(series, col: str, rec: _Recorder) -> list:
    out = []
    for idx, v in series.items():
        if _is_na(v):
            out.append(None)
            continue
        low = v.lower()
        if not _EMAIL_RE.match(low) or low in _PLACEHOLDER_EMAILS:
            rec.log(idx, col, v, None, R_EMAIL)
            out.append(None)
            continue
        if low != v:
            rec.log(idx, col, v, low, R_CASE)
        out.append(low)
    return out


def _clean_phone_col(series, col: str, rec: _Recorder) -> list:
    out = []
    for idx, v in series.items():
        if _is_na(v):
            out.append(None)
            continue
        cleaned = _clean_phone(v)
        if cleaned is None:
            rec.log(idx, col, v, None, R_PHONE_BAD)
        elif cleaned != v:
            rec.log(idx, col, v, cleaned, R_PHONE)
        out.append(cleaned)
    return out


def _clean_date_col(series, col: str, rec: _Recorder, flags: list[str]) -> list:
    values = [v for v in series if not _is_na(v)]
    dayfirst, ambiguous = _dayfirst_for(values)
    parsed = {idx: (_parse_date(v, dayfirst) if not _is_na(v) else None) for idx, v in series.items()}
    with_time = any(p and (p.hour or p.minute or p.second) for p in parsed.values())
    fmt = "%Y-%m-%d %H:%M:%S" if with_time else "%Y-%m-%d"
    if ambiguous:
        order = "day-first (dd/mm/yyyy)" if dayfirst else "month-first (mm/dd/yyyy)"
        flags.append(f"{col}: {ambiguous} date(s) such as 07-08-2025 are ambiguous and were read as {order}.")
    out = []
    for idx, v in series.items():
        if _is_na(v):
            out.append(None)
        elif parsed[idx] is None:
            rec.log(idx, col, v, None, R_DATE_BAD)
            out.append(None)
        else:
            text = parsed[idx].strftime(fmt)
            if text != v:
                rec.log(idx, col, v, text, R_DATE)
            out.append(text)
    return out


def _numeric_bounds(col: str):
    toks = _tokens(col)
    if "age" in toks:
        return 1, 120
    if toks & _MONEY_TOKENS:
        return 0, None
    return None, None


def _clean_number_col(series, col: str, rec: _Recorder):
    """Returns (values, decimals) where decimals is None for an integer column."""
    low, high = _numeric_bounds(col)
    parsed: dict[int, float | None] = {}
    max_decimals = 0
    saw_point = False
    for idx, v in series.items():
        if _is_na(v):
            parsed[idx] = None
            continue
        result = _to_number(v)
        if result is None:
            rec.log(idx, col, v, None, R_NUM_BAD)
            parsed[idx] = None
            continue
        num, plain = result
        if (low is not None and num < low) or (high is not None and num > high):
            rec.log(idx, col, v, None, R_RANGE)
            parsed[idx] = None
            continue
        if not plain:
            rec.log(idx, col, v, num, R_NUM_FMT)
        if "." in v:
            saw_point = True
            max_decimals = max(max_decimals, len(v.split(".")[-1]))
        parsed[idx] = num
    integral = not saw_point and all(p is None or p.is_integer() for p in parsed.values())
    if integral:
        return [None if p is None else int(p) for p in parsed.values()], None
    decimals = min(max(max_decimals, 1), 6)
    return [None if p is None else round(p, decimals) for p in parsed.values()], decimals


def _canonical_map(values: list[str], column_is_consistent: bool) -> dict[str, str]:
    """Map every variant of a text value to one canonical spelling."""
    groups: dict[str, Counter] = defaultdict(Counter)
    for v in values:
        groups[v.casefold()][v] += 1
    canon: dict[str, str] = {}
    for variants in groups.values():
        mixed = [v for v in variants if not _is_mono(v)]
        pool = mixed or list(variants)
        best = max(pool, key=lambda v: (variants[v], v))
        recase = _is_mono(best) and not column_is_consistent and not (best.isupper() and len(best) <= 3)
        if recase:
            best = _smart_title(best)
        for v in variants:
            canon[v] = best
    return canon


def _clean_text_col(series, col: str, kind: str, rec: _Recorder) -> list:
    aliases = _GENDERS if kind == "gender" else _SA_PROVINCES if kind == "province" else None
    stage = []
    for idx, v in series.items():
        if _is_na(v):
            stage.append(None)
            continue
        v2 = _WS.sub(" ", v) if kind != "free_text" else v
        if v2 != v:
            rec.log(idx, col, v, v2, R_WS)
        if aliases is not None:
            mapped = aliases.get(v2.lower() if kind == "gender" else re.sub(r"[^a-z]", "", v2.lower()))
            if mapped and mapped != v2:
                rec.log(idx, col, v2, mapped, R_CATEGORY)
                v2 = mapped
        stage.append(v2)
    if kind == "free_text":
        return [None if _is_na(v) else _neutralise_formula(i, col, v, rec) for i, v in zip(series.index, stage)]

    present = [v for v in stage if not _is_na(v)]
    mono_share = _ratio(present, _is_mono)
    canon = _canonical_map(present, column_is_consistent=mono_share >= 0.9)
    out = []
    for idx, v in zip(series.index, stage):
        if _is_na(v):
            out.append(None)
            continue
        final = canon[v]
        if final != v:
            rec.log(idx, col, v, final, R_CASE)
        out.append(_neutralise_formula(idx, col, final, rec))
    return out


# ── dedupe / flags ────────────────────────────────────────────────────────────

def _find_duplicates(cleaned, primary_keys: list[str]) -> list[tuple[int, int]]:
    """Return (duplicate_idx, first_idx). Ids are ignored when other columns identify a record."""
    subset = [c for c in cleaned.columns if c not in primary_keys]
    if len(subset) < 2:
        subset = list(cleaned.columns)
    first_seen: dict[tuple, int] = {}
    dupes = []
    for idx, row in enumerate(cleaned[subset].itertuples(index=False, name=None)):
        key = tuple(None if _is_na(v) else v for v in row)
        if all(k is None for k in key):
            continue
        if key in first_seen:
            dupes.append((idx, first_seen[key]))
        else:
            first_seen[key] = idx
    return dupes


def _sparse_rows(cleaned, primary_keys: list[str]) -> list[int]:
    cols = [c for c in cleaned.columns if c not in primary_keys]
    if len(cols) < 4:
        return []
    limit = 0.6 * len(cols)
    return [i + 2 for i, row in enumerate(cleaned[cols].isna().to_numpy().tolist()) if sum(row) >= limit]


# ── public API ────────────────────────────────────────────────────────────────

def clean_with_report(df, *, dedupe: bool = True):
    """Clean a DataFrame. Returns (cleaned_df, report_dict). The input is not modified."""
    import pandas as pd

    rec = _Recorder()
    work = _to_text_frame(df)
    rows_before = len(work)

    for col in work.columns:
        work[col] = _strip_and_null(work[col], col, rec)
    missing_by_column = {c: int(work[c].isna().sum()) for c in work.columns if work[c].isna().any()}

    empty_cols = [c for c in work.columns if work[c].isna().all()]
    empty_rows = [i for i in work.index if work.loc[i].isna().all()]
    kinds: dict[str, str] = {}
    display_kinds: dict[str, str] = {}
    for col in work.columns:
        values = [v for v in work[col] if not _is_na(v)]
        kinds[col] = _classify(col, values)
        display_kinds[col] = _display_kind(kinds[col], values)

    flags: list[str] = []
    decimals: dict[str, int] = {}
    cleaned = pd.DataFrame(index=work.index)
    for col in work.columns:
        if col in empty_cols:
            continue
        kind, series = kinds[col], work[col]
        if kind == "email":
            cleaned[col] = _clean_email(series, col, rec)
        elif kind == "phone":
            cleaned[col] = _clean_phone_col(series, col, rec)
        elif kind == "date":
            cleaned[col] = _clean_date_col(series, col, rec, flags)
        elif kind == "number":
            values, dec = _clean_number_col(series, col, rec)
            cleaned[col] = pd.array(values, dtype="Int64") if dec is None else pd.array(values, dtype="Float64")
            if dec is not None:
                decimals[col] = dec
        elif kind == "id":
            cleaned[col] = list(series)
        else:
            cleaned[col] = _clean_text_col(series, col, kind, rec)

    cleaned = cleaned.drop(index=empty_rows)
    primary_keys = [c for c in cleaned.columns if kinds[c] == "id" and cleaned[c].notna().all() and cleaned[c].is_unique]

    removed: list[dict] = []
    duplicates_removed = 0
    if dedupe:
        dupes = _find_duplicates(cleaned, primary_keys)
        duplicates_removed = len(dupes)
        removed = [{"row": d + 2, "duplicate_of_row": f + 2} for d, f in dupes[:MAX_LOGGED_CHANGES]]
        cleaned = cleaned.drop(index=cleaned.index[[d for d, _ in dupes]])

    sparse = _sparse_rows(cleaned, primary_keys)
    if sparse:
        shown = ", ".join(str(r) for r in sparse[:10])
        flags.append(f"{len(sparse)} row(s) are mostly empty after cleaning (file rows {shown}{'…' if len(sparse) > 10 else ''}) — review before use.")

    cleaned = cleaned.reset_index(drop=True)
    cleaned.attrs["decimals"] = decimals
    report = {
        "rows_before": rows_before,
        "rows_after": len(cleaned),
        "empty_rows_removed": len(empty_rows),
        "empty_columns_removed": empty_cols,
        "duplicates_removed": duplicates_removed,
        "removed_rows": removed,
        "summary": rec.summary(),
        "changes": rec.changes,
        "changes_truncated": sum(s["count"] for s in rec.summary()) > len(rec.changes),
        "flags": flags,
        "column_types": display_kinds,
        "missing_by_column": missing_by_column,
        "columns": list(work.columns),
        "unique_by_column": {c: int(work[c].nunique(dropna=True)) for c in work.columns},
    }
    return cleaned, report


def clean_dataframe(df):
    """Backwards-compatible wrapper returning only the cleaned DataFrame."""
    return clean_with_report(df)[0]


def profile_dataframe(df) -> dict:
    """Describe what is wrong with a DataFrame (a dry run of the cleaner)."""
    _, report = clean_with_report(df)
    issues = []
    ws_cols: list[str] = []
    for item in report["summary"]:
        cols = ", ".join(item["columns"])
        issues.append(f"{item['reason']}: {item['count']} in {cols}")
        if item["reason"] == R_WS:
            ws_cols = item["columns"]
    if report["duplicates_removed"]:
        issues.append(f"{R_DUP}: {report['duplicates_removed']}")
    for flag in report["flags"]:
        issues.append(flag)
    missing = report["missing_by_column"]
    return {
        "rows": report["rows_before"],
        "columns": len(report["columns"]),
        "column_names": report["columns"],
        "null_cols": missing,
        "null_count": sum(missing.values()),
        "duplicate_rows": report["duplicates_removed"],
        "whitespace_cols": ws_cols,
        "issues": issues,
        "issue_count": len(issues),
        "column_profiles": [
            {
                "name": c,
                "dtype": report["column_types"][c],
                "null_count": missing.get(c, 0),
                "unique_count": report["unique_by_column"][c],
            }
            for c in report["columns"]
        ],
    }


# ── IO ────────────────────────────────────────────────────────────────────────

def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def parse_upload(data: bytes, filename: str):
    """Read uploaded bytes into a DataFrame. Supports CSV, XLS, XLSX, JSON."""
    import pandas as pd

    ext = Path(filename).suffix.lower()
    if ext == ".csv":
        text = _decode(data)
        try:
            sep = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
        except csv.Error:
            sep = ","
        return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)
    if ext in (".xlsx", ".xls"):
        engine = "openpyxl" if ext == ".xlsx" else "xlrd"
        return pd.read_excel(io.BytesIO(data), engine=engine, dtype=str, keep_default_na=False)
    if ext == ".json":
        return pd.read_json(io.BytesIO(data), dtype=False)
    raise ValueError(f"Unsupported file type: {ext}")


def dataframe_to_bytes(df, filename: str) -> tuple[bytes, str]:
    """Serialise a cleaned DataFrame back to bytes. Returns (bytes, media_type)."""
    ext = Path(filename).suffix.lower()
    out = df.copy()
    for col, places in df.attrs.get("decimals", {}).items():
        out[col] = [None if _is_na(v) or v is None or str(v) == "<NA>" else f"{float(v):.{places}f}" for v in out[col]]
    buf = io.BytesIO()
    if ext in (".xlsx", ".xls"):
        out.to_excel(buf, index=False, engine="openpyxl")
        return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    out.to_csv(buf, index=False)
    return buf.getvalue(), "text/csv"


def generate_cleaning_script(filename: str, profile: dict | None = None) -> str:
    """A standalone script: this module's source plus a small runner (needs only pandas)."""
    source = Path(__file__).read_text(encoding="utf-8")
    runner = '''

if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "input_file"
    cleaned, report = clean_with_report(parse_upload(Path(path).read_bytes(), path))
    out_bytes, _ = dataframe_to_bytes(cleaned, path)
    out_path = "cleaned_output" + Path(path).suffix
    Path(out_path).write_bytes(out_bytes)
    print(f"Done: {report['rows_before']} -> {report['rows_after']} rows, saved to {out_path}")
    for item in report["summary"]:
        print(f"  - {item['reason']}: {item['count']} ({', '.join(item['columns'])})")
    for flag in report["flags"]:
        print("  ! " + flag)
'''
    header = f'# Cleaning script generated by Aria for "{Path(filename).name}".\n# Usage: python this_script.py your_file.csv\n'
    return header + source + runner

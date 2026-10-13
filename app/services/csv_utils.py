"""Small helper shared by CSV importers."""
import pandas as pd

from app.validation import ValidationError

MAX_CSV_ROWS = 20000


def read_csv_required(source, required: list) -> pd.DataFrame:
    """Reads a CSV (path or file-like). Raises ValidationError with a clear message."""
    try:
        df = pd.read_csv(source, dtype=str, keep_default_na=False, encoding="utf-8-sig", nrows=MAX_CSV_ROWS + 1)
    except pd.errors.EmptyDataError:
        raise ValidationError("The CSV file is empty.")
    except UnicodeDecodeError:
        raise ValidationError("The file is not UTF-8 text. In Excel use 'Save As' -> 'CSV UTF-8'.")
    except pd.errors.ParserError as e:
        raise ValidationError(f"The CSV could not be read: {e}")

    if len(df) > MAX_CSV_ROWS:
        raise ValidationError(f"The CSV has more than {MAX_CSV_ROWS:,} rows. Please split it into smaller files.")
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValidationError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Columns found: {', '.join(df.columns)}."
        )
    if df.empty:
        raise ValidationError("The CSV has a header row but no data rows.")
    df = df.fillna("")
    for column in df.columns:
        df[column] = df[column].astype(str).str.strip()
    return df

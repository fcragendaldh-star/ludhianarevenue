# app.py  — Ludhiana District Revenue Dashboard
# Multi-agenda monitoring dashboard for DC Review
# Developed by: Shivam Gulati, Land Revenue Fellow

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import re
import time
import logging
import os
import html
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo

from agenda_config import AGENDAS, AGENDA_MAP

# ─────────────────────────────── logging ────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────── page config ────────────────────────────────
st.set_page_config(
    page_title="Ludhiana Revenue Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"About": "Ludhiana District Revenue Dashboard — DC Review Tool"},
)

# ─────────────────────────────── constants ──────────────────────────────────
DATA_FOLDER_BASE = Path("data")
FILENAME_DATE_RE = re.compile(r"(\d{8})")   # YYYYMMDD
DATE_FORMAT = "%Y%m%d"
APP_TIMEZONE = ZoneInfo("Asia/Kolkata")

# ─────────────────────────────── Google Drive ───────────────────────────────
GOOGLE_DRIVE_AVAILABLE = False
try:
    from google_drive_storage import GoogleDriveStorage
    GOOGLE_DRIVE_AVAILABLE = True
except Exception as e:
    logger.warning(f"Google Drive module not importable: {e}")


def _secret_to_plain(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return dict(value)
    return value


def _get_credentials_json():
    """Retrieve service account credentials from Streamlit secrets or env."""
    for secret_key in (
        "GOOGLE_APPLICATION_CREDENTIALS_JSON",
        "gcp_service_account",
        "google_service_account",
        "service_account",
    ):
        try:
            creds = st.secrets.get(secret_key)
        except Exception:
            creds = None
        if creds:
            return _secret_to_plain(creds)

    try:
        root_secrets = st.secrets.to_dict()
        if root_secrets.get("type") == "service_account":
            return root_secrets
    except Exception:
        pass

    return os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "")


def _get_folder_id(secret_key: str, default: str = "") -> str:
    """Retrieve a per-agenda folder ID from Streamlit secrets or env."""
    try:
        folder_id = st.secrets[secret_key]
    except Exception:
        folder_id = os.getenv(secret_key, "")
    return folder_id or default


def drive_status_message(agenda: dict) -> str:
    folder_id = _get_folder_id(agenda["folder_secret"], agenda.get("folder_id", ""))
    if not GOOGLE_DRIVE_AVAILABLE:
        return "Google Drive libraries are not available. Check requirements installation."
    if not folder_id:
        return f"Google Drive folder ID is missing for {agenda['folder_secret']}."
    if not _get_credentials_json():
        return (
            "Google Drive credentials are missing. Add GOOGLE_APPLICATION_CREDENTIALS_JSON "
            "or a [gcp_service_account] block in Streamlit secrets."
        )
    return (
        "Google Drive is configured. If data is still empty, share this Drive folder "
        "with the service account email and click Refresh All."
    )


# ─────────────────────────────── helpers ────────────────────────────────────

def fmt(num) -> str:
    try:
        return f"{int(num):,}"
    except Exception:
        return "0"


def current_app_time_label() -> str:
    return datetime.now(APP_TIMEZONE).strftime("%d %b %Y, %I:%M %p IST")


def pct_change(current, previous) -> float:
    if previous == 0:
        return 0.0 if current == 0 else 100.0
    return ((current - previous) / previous) * 100


def trend_icon(change: float) -> str:
    return "📈" if change > 0 else ("📉" if change < 0 else "➡️")


def validate_df(df: pd.DataFrame, group_cols: list) -> tuple[bool, str]:
    if df.empty:
        return False, "File is empty"
    
    # Check if at least one grouping column is present (ignore accidental spaces)
    normalized_cols = {str(c).strip() for c in df.columns}
    has_group_col = any(str(col).strip() in normalized_cols for col in group_cols)
    if not has_group_col:
        return False, f"Missing grouping columns. Expected at least one of: {group_cols}"
    
    return True, "OK"


def clean_col_name(col) -> str:
    """Normalize Excel header whitespace without changing meaningful wording."""
    return str(col).replace("\xa0", " ").strip()


def configured_cols(agenda: dict, key: str, fallback_key: str = "columns") -> list[str]:
    cols = agenda.get(key) or agenda.get(fallback_key, [])
    return list(dict.fromkeys(clean_col_name(c) for c in cols))


def available_metric_cols(df: pd.DataFrame, agenda: dict, key: str, fallback_key: str = "columns") -> list[str]:
    return [c for c in configured_cols(agenda, key, fallback_key) if c in df.columns]


def usable_group_col(df: pd.DataFrame, agenda: dict) -> str:
    """Pick the best grouping column for this agenda and loaded file."""
    candidates = []
    for col in [agenda.get("group_label"), *agenda.get("group_cols", []),
                "Sub Division", "Tehsil/Sub Tehsil", "Sub-Tehsil", "District", "Officer"]:
        if col and col not in candidates:
            candidates.append(col)

    for col in candidates:
        if col not in df.columns:
            continue
        values = df[col].dropna().astype(str).str.strip()
        values = values[~values.str.lower().isin(["", "unknown", "n/a", "nan"])]
        if not values.empty:
            return col
    return "Sub Division" if "Sub Division" in df.columns else df.columns[0]


def useful_nunique(df: pd.DataFrame, col: str) -> int:
    if col not in df.columns:
        return 0
    values = df[col].dropna().astype(str).str.strip()
    values = values[~values.str.lower().isin(["", "unknown", "n/a", "nan"])]
    return int(values.nunique())


def esc(value) -> str:
    return html.escape(str(value))


def metric_sum(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())


def delta_label(current: float, previous: float | None) -> str | None:
    if previous is None:
        return None
    diff = current - previous
    if previous == 0:
        pct = 0.0 if current == 0 else 100.0
    else:
        pct = diff / previous * 100
    return f"{diff:+,.0f} ({pct:+.1f}%)"


def snapshot_label(df: pd.DataFrame) -> pd.Series:
    dated = pd.to_datetime(df["__date"], errors="coerce")
    if dated.notna().any():
        return dated.dt.strftime("%d %b %Y").fillna(df["__source"].astype(str))
    return df["__source"].astype(str)


def traffic_signal_color(value: float, max_value: float) -> str:
    if max_value <= 0:
        return "#43a047"
    ratio = value / max_value
    if ratio >= 0.67:
        return "#d32f2f"
    if ratio >= 0.34:
        return "#f9a825"
    return "#43a047"


# ─────────────────────────────── data loader ────────────────────────────────

def _load_agenda_files(agenda: dict, max_files: int = 10) -> pd.DataFrame:
    """
    Load the most recent Excel files for a given agenda.
    Tries Google Drive first, falls back to local data/<agenda_key>/ folder.
    """
    rows = []
    failed = []
    agenda_key = agenda["key"]
    pendency_cols = configured_cols(agenda, "columns")
    total_cols = configured_cols(agenda, "total_columns")
    breakdown_cols = configured_cols(agenda, "breakdown_columns")
    group_cols = [clean_col_name(c) for c in agenda["group_cols"]]
    metric_cols = list(dict.fromkeys([
        *pendency_cols,
        *total_cols,
        *breakdown_cols,
        clean_col_name(agenda.get("target_col", "Total")),
    ]))

    # ── Google Drive ──
    use_drive = False
    storage = None
    if GOOGLE_DRIVE_AVAILABLE:
        folder_id = _get_folder_id(agenda["folder_secret"], agenda.get("folder_id", ""))
        creds_json = _get_credentials_json()
        if folder_id and creds_json:
            try:
                storage = GoogleDriveStorage(folder_id=folder_id, credentials_json=creds_json)
                use_drive = True
            except Exception as e:
                logger.warning(f"[{agenda_key}] Drive init failed: {e}")

    if use_drive and storage:
        drive_files = storage.list_files()
        excel_files = [
            f for f in drive_files
            if f["name"].lower().endswith((".xlsx", ".xls"))
            or f.get("mimeType") == "application/vnd.google-apps.spreadsheet"
        ]

        def _date_key(f):
            m = FILENAME_DATE_RE.search(f["name"])
            if m:
                try:
                    ts = pd.to_datetime(m.group(1), format=DATE_FORMAT)
                    return (ts, f["name"].lower())
                except Exception:
                    pass
            modified = pd.to_datetime(f.get("modifiedTime"), errors="coerce")
            fallback = modified if pd.notna(modified) else pd.Timestamp.min
            return (fallback, f["name"].lower())

        excel_files = sorted(excel_files, key=_date_key)[-max_files:]
        for drv_file in excel_files:
            fname = drv_file["name"]
            try:
                data = storage.download_file(drv_file["id"], drv_file.get("mimeType", ""))
                if not data.getvalue():
                    failed.append((fname, "empty")); continue
                df = pd.read_excel(data, engine="openpyxl")
                df = _normalise_df(df, fname, pendency_cols, group_cols)
                if df is not None:
                    rows.append(df)
            except Exception as e:
                logger.error(f"[{agenda_key}] {fname}: {e}")
                failed.append((fname, str(e)))

    # ── Local fallback ──
    if not rows:
        folder_name = agenda.get("folder_name", agenda_key)
        local_dir = DATA_FOLDER_BASE / folder_name
        local_dir.mkdir(parents=True, exist_ok=True)
        local_files = [f for f in local_dir.glob("*.xlsx") if not f.name.startswith("~$")]

        def _local_date_key(path_obj):
            m = FILENAME_DATE_RE.search(path_obj.name)
            if m:
                try:
                    ts = pd.to_datetime(m.group(1), format=DATE_FORMAT)
                    return (ts, path_obj.name.lower())
                except Exception:
                    pass
            modified = pd.to_datetime(path_obj.stat().st_mtime, unit="s", errors="coerce")
            fallback = modified if pd.notna(modified) else pd.Timestamp.min
            return (fallback, path_obj.name.lower())

        local_files = sorted(local_files, key=_local_date_key)[-max_files:]
        for f in local_files:
            try:
                df = pd.read_excel(f, engine="openpyxl")
                df = _normalise_df(df, f.name, pendency_cols, group_cols)
                if df is not None:
                    rows.append(df)
            except Exception as e:
                logger.error(f"[{agenda_key}] {f.name}: {e}")
                failed.append((f.name, str(e)))

    if not rows:
        return pd.DataFrame()

    combined = pd.concat(rows, ignore_index=True, sort=False)

    # Ensure all configured metric columns exist and are numeric
    for col in metric_cols:
        if not col or col == "Total":
            continue
        if col not in combined.columns:
            combined[col] = 0
        combined[col] = pd.to_numeric(combined[col], errors="coerce").fillna(0)

    # Compute / overwrite Total from comparable workload columns only.
    valid_total_cols = [c for c in total_cols if c in combined.columns]
    if not valid_total_cols:
        valid_total_cols = [c for c in pendency_cols if c in combined.columns]
    combined["Total"] = combined[valid_total_cols].sum(axis=1)

    # Fill blanks for common columns
    for col in ["Sub Division", "Officer", "District"]:
        if col not in combined.columns:
            combined[col] = "Unknown"
    if "Tehsil/Sub Tehsil" not in combined.columns and "Sub-Tehsil" not in combined.columns:
        combined["Tehsil/Sub Tehsil"] = "N/A"

    if failed:
        logger.warning(f"[{agenda_key}] Failed files: {failed}")
    return combined


def _normalise_df(df: pd.DataFrame, fname: str, pendency_cols: list, group_cols: list):
    """Normalise column names and inject date/source metadata."""
    if df.empty:
        return None

    # Normalize accidental header spaces from Excel exports
    df.columns = [clean_col_name(c) for c in df.columns]

    # Fuzzy rename common column variations
    column_mappings = {
        "Sub Division": ["sub division", "sub-division", "sub div", "subdiv", "sub division "],
        "Sub-Tehsil": ["sub tehsil", "sub-tehsil", "tehsil/sub tehsil", "sub tehsil "],
        "Officer": ["officer", "officer ", "officer "],
        "District": ["district"],
        "Tehsil/Sub Tehsil": ["tehsil/sub tehsil", "tehsil/sub-tehsil", "tehsil", "tehsil/sub tehsil "],
    }
    
    for standard_name, variations in column_mappings.items():
        if standard_name not in df.columns:
            for variation in variations:
                matches = [c for c in df.columns if variation.strip() in c.lower().strip()]
                if matches:
                    df.rename(columns={matches[0]: standard_name}, inplace=True)
                    break

    if "Sub-Tehsil" in df.columns and "Tehsil/Sub Tehsil" not in df.columns:
        df["Tehsil/Sub Tehsil"] = df["Sub-Tehsil"]
    if "Tehsil/Sub Tehsil" in df.columns and "Sub-Tehsil" not in df.columns:
        df["Sub-Tehsil"] = df["Tehsil/Sub Tehsil"]

    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)

    ok, msg = validate_df(df, group_cols)
    if not ok:
        logger.warning(f"  Skipping {fname}: {msg}")
        return None

    m = FILENAME_DATE_RE.search(fname)
    file_date = pd.to_datetime(m.group(1), format=DATE_FORMAT) if m else pd.NaT
    df["__source"] = fname
    df["__date"] = file_date
    return df


@st.cache_data(ttl=1800, show_spinner=False)
def load_agenda(agenda_key: str, cache_ver: str = "v1") -> pd.DataFrame:
    return _load_agenda_files(AGENDA_MAP[agenda_key])


# ─────────────────────────────── CSS ────────────────────────────────────────

def inject_css():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

*, *::before, *::after { box-sizing: border-box; }

html, body, .stApp {
    font-family: 'DM Sans', sans-serif;
    background: #f4f6f9;
}

/* ── Header ── */
.dash-header {
    background: linear-gradient(135deg, #0a2240 0%, #1a4b8c 60%, #1565c0 100%);
    padding: 1.4rem 2rem 1.2rem;
    border-radius: 12px;
    margin-bottom: 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    box-shadow: 0 4px 20px rgba(10,34,64,0.25);
}
.dash-header h1 {
    color: #fff !important;
    font-size: 1.6rem !important;
    font-weight: 700 !important;
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    letter-spacing: 0.3px;
}
.dash-header .subtitle {
    color: rgba(255,255,255,0.72);
    font-size: 0.82rem;
    margin-top: 0.2rem;
    font-weight: 400;
}
.header-badge {
    background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.3);
    border-radius: 8px;
    padding: 0.4rem 0.9rem;
    color: #fff;
    font-size: 0.8rem;
    font-weight: 500;
    white-space: nowrap;
}

/* ── Tab bar ── */
.stTabs [data-baseweb="tab-list"] {
    background: #fff;
    border-radius: 10px;
    padding: 0.35rem;
    gap: 0.25rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    margin-bottom: 1.2rem;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 0.55rem 1.1rem;
    font-size: 0.88rem;
    font-weight: 500;
    color: #546e7a;
    transition: all 0.2s ease;
    border: none !important;
}
.stTabs [aria-selected="true"] {
    background: #0a2240 !important;
    color: #fff !important;
    font-weight: 600 !important;
}
.stTabs [data-baseweb="tab-highlight"] { display: none; }
.stTabs [data-baseweb="tab-border"] { display: none; }

/* ── Metric cards ── */
[data-testid="stMetricContainer"] {
    background: #fff;
    border-radius: 10px;
    padding: 1rem 1.2rem !important;
    box-shadow: 0 1px 6px rgba(0,0,0,0.07);
    border: 1px solid #e8ecf0;
}
[data-testid="stMetricValue"] {
    font-size: 1.9rem !important;
    font-weight: 700 !important;
    color: #0a2240 !important;
    font-family: 'DM Mono', monospace !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.8rem !important;
    color: #78909c !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
[data-testid="stMetricDelta"] { font-size: 0.85rem !important; }

/* ── Agenda header card ── */
.agenda-header {
    background: #fff;
    border-radius: 10px;
    padding: 1rem 1.4rem;
    margin-bottom: 1.2rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    border-left: 5px solid var(--agenda-color, #1565c0);
    box-shadow: 0 1px 6px rgba(0,0,0,0.06);
}
.agenda-icon { font-size: 2rem; line-height: 1; }
.agenda-title { font-size: 1.15rem; font-weight: 700; color: #0a2240; margin: 0; }
.agenda-desc { font-size: 0.82rem; color: #78909c; margin: 0.15rem 0 0; }

/* ── Section headers ── */
h2 {
    color: #0a2240 !important;
    font-size: 1rem !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin: 1.4rem 0 0.8rem !important;
    padding-bottom: 0.4rem !important;
    border-bottom: 2px solid #e3e8ef !important;
}
h3 {
    color: #1a3a5c !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    margin: 1rem 0 0.5rem !important;
}

/* ── Data table ── */
.stDataFrame { border-radius: 8px; overflow: hidden; }
.stDataFrame thead th {
    background: #f0f4f8 !important;
    font-size: 0.78rem !important;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    color: #546e7a !important;
}

/* Lowest progress officer tabs */
.lowest-progress-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.75rem;
    align-items: start;
}
.lowest-progress-panel h4 {
    color: #1d2733;
    font-size: 1.05rem;
    font-weight: 700;
    margin: 0 0 0.55rem;
}
.officer-progress-tab {
    background: #fff;
    border: 1px solid #ffcdd2;
    border-radius: 8px;
    margin-bottom: 0.5rem;
    overflow: hidden;
    box-shadow: 0 1px 6px rgba(183,28,28,0.11);
}
.officer-progress-tab-title {
    background: #c62828;
    color: #fff;
    font-size: 0.86rem;
    font-weight: 800;
    line-height: 1.25;
    padding: 0.45rem 0.65rem;
}
.officer-progress-meta {
    color: #6b7785;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 0.4rem 0.65rem 0;
}
.officer-progress-stats {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.35rem;
    padding: 0.45rem 0.65rem 0.5rem;
}
.officer-progress-stat {
    background: #fafbfc;
    border: 1px solid #edf0f3;
    border-radius: 6px;
    padding: 0.35rem 0.45rem;
    min-width: 0;
}
.officer-progress-stat span {
    display: block;
    color: #7b8794;
    font-size: 0.58rem;
    font-weight: 700;
    text-transform: uppercase;
}
.officer-progress-stat strong {
    display: block;
    color: #0a2240;
    font-family: 'DM Mono', monospace;
    font-size: 0.88rem;
    margin-top: 0.1rem;
}
.officer-progress-status {
    display: inline-block;
    margin: 0 0.65rem 0.55rem;
    border-radius: 999px;
    padding: 0.22rem 0.55rem;
    font-size: 0.65rem;
    font-weight: 800;
}
.officer-progress-status.worsened {
    background: #ffebee;
    color: #b71c1c;
}
.officer-progress-status.no-progress {
    background: #fff3e0;
    color: #bf360c;
}
.officer-progress-status.low-progress {
    background: #fffde7;
    color: #6d4c00;
}

/* ── Charts ── */
.js-plotly-plot {
    border-radius: 10px;
    background: #fff;
    box-shadow: 0 1px 6px rgba(0,0,0,0.06);
    padding: 0.5rem;
}

/* ── Alert / info boxes ── */
.stAlert { border-radius: 8px; }
.stSuccess { border-left: 4px solid #2e7d32; }
.stWarning { border-left: 4px solid #e65100; }
.stError   { border-left: 4px solid #c62828; }
.stInfo    { border-left: 4px solid #0277bd; }

/* ── Buttons ── */
.stButton > button {
    background: #0a2240 !important;
    color: #fff !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    padding: 0.5rem 1.2rem !important;
    font-size: 0.88rem !important;
    transition: all 0.2s !important;
}
.stButton > button:hover {
    background: #1a4b8c !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(10,34,64,0.25) !important;
}

/* ── Download button ── */
.stDownloadButton > button {
    background: #f0f4f8 !important;
    color: #0a2240 !important;
    border: 1px solid #c5d0dc !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
}

/* ── Footer ── */
.dash-footer {
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid #dde3ea;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.78rem;
    color: #90a4ae;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] { background: #fff; }

/* ── Responsive ── */
@media (max-width: 768px) {
    .dash-header { flex-direction: column; align-items: flex-start; gap: 0.5rem; }
    .dash-header h1 { font-size: 1.2rem !important; }
    [data-testid="stMetricValue"] { font-size: 1.4rem !important; }
    .stTabs [data-baseweb="tab"] { padding: 0.45rem 0.75rem; font-size: 0.8rem; }
    .lowest-progress-grid { grid-template-columns: 1fr; }
    .officer-progress-stats { grid-template-columns: 1fr; }
}

/* ── Pendency type mini-card ── */
.ptype-card {
    border-radius: 8px;
    padding: 0.7rem 0.9rem;
    margin-bottom: 0.5rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}
.ptype-name { font-size: 0.75rem; font-weight: 600; margin: 0 0 0.25rem; opacity: 0.85; }
.ptype-val  { font-size: 1.3rem; font-weight: 700; margin: 0; font-family: 'DM Mono', monospace; }
.ptype-pct  { font-size: 0.72rem; margin: 0.1rem 0 0; opacity: 0.8; }

/* ── No-data placeholder ── */
.no-data {
    background: #fff;
    border-radius: 10px;
    padding: 3rem 2rem;
    text-align: center;
    color: #90a4ae;
    border: 2px dashed #dde3ea;
}
.no-data h3 { color: #78909c !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────── components ─────────────────────────────────

def render_agenda_header(agenda: dict):
    color = agenda["color"]
    st.markdown(f"""
    <div class="agenda-header" style="--agenda-color:{color};">
        <div class="agenda-icon">{agenda["icon"]}</div>
        <div>
            <p class="agenda-title">{agenda["label"]}</p>
            <p class="agenda-desc">{agenda["description"]}</p>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_no_data(agenda: dict):
    secret = agenda["folder_secret"]
    folder_name = agenda.get("folder_name", agenda["key"])
    st.markdown(f"""
    <div class="no-data">
        <h3>No Data Available</h3>
        <p>Upload Excel files to Google Drive folder configured under<br>
        <code>{secret}</code><br><br>
        Or place <code>.xlsx</code> files in <code>data/{folder_name}/</code> for local testing.</p>
    </div>
    """, unsafe_allow_html=True)
    st.info(drive_status_message(agenda))


def render_kpi_row(df_latest: pd.DataFrame, df_prev: pd.DataFrame, agenda: dict):
    target_col = agenda["target_col"]
    lower_better = agenda["target_type"] == "lower_better"
    metric_col = target_col if target_col in df_latest.columns else "Total"
    group_col = usable_group_col(df_latest, agenda)

    metric_now = float(df_latest[metric_col].sum()) if metric_col in df_latest.columns else 0.0
    metric_prev = float(df_prev[metric_col].sum()) if not df_prev.empty and metric_col in df_prev.columns else 0.0
    chg = pct_change(metric_now, metric_prev)

    n_groups = useful_nunique(df_latest, group_col)
    n_officers = useful_nunique(df_latest, "Officer")

    threshold = agenda["alert_threshold"]
    agg_sub = df_latest.groupby(group_col, as_index=False)[metric_col].sum()
    if lower_better:
        n_alerts = int((agg_sub[metric_col] > threshold).sum())
    else:
        n_alerts = int((agg_sub[metric_col] < threshold).sum())

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        delta = f"{chg:+.1f}%" if metric_prev else None
        # For lower_better pendency: increase (positive %) is bad → delta_color="inverse"
        st.metric("Total" if metric_col == "Total" else metric_col,
                  fmt(metric_now), delta=delta,
                  delta_color="inverse" if lower_better else "normal")
    with c2:
        st.metric(group_col, n_groups)
    with c3:
        st.metric("Officers", n_officers)
    with c4:
        if n_alerts:
            st.metric("⚠️ Alerts", n_alerts, delta="Action needed", delta_color="inverse")
        else:
            st.metric("✅ Alerts", "0", delta="All clear", delta_color="off")


def render_pendency_breakdown(df_latest: pd.DataFrame, agenda: dict):
    cols = available_metric_cols(df_latest, agenda, "breakdown_columns", "total_columns")
    if not cols:
        return
    totals = {c: float(df_latest[c].sum()) for c in cols}
    grand = sum(totals.values()) or 1

    sorted_cols = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    color = agenda["color"]

    # Build a gradient of the agenda color
    n = len(sorted_cols)
    per_row = 4 if n > 4 else n
    for i in range(0, n, per_row):
        chunk = sorted_cols[i:i + per_row]
        r_cols = st.columns(len(chunk))
        for j, (name, val) in enumerate(chunk):
            pct = val / grand * 100
            opacity = max(0.15, 1 - j * 0.12)
            with r_cols[j]:
                st.markdown(f"""
                <div class="ptype-card" style="background:{color}{int(opacity*255):02x}; color:#0a2240;">
                    <p class="ptype-name">{name}</p>
                    <p class="ptype-val">{fmt(val)}</p>
                    <p class="ptype-pct">{pct:.1f}% of shown workload</p>
                </div>""", unsafe_allow_html=True)


def render_charts(df_all: pd.DataFrame, df_latest: pd.DataFrame, agenda: dict):
    color = agenda["color"]
    group_col = usable_group_col(df_latest, agenda)

    col_trend, col_dist = st.columns(2)

    with col_trend:
        st.markdown("### 📈 Trend Over Time")
        trend = df_all.groupby("__date", as_index=False)["Total"].sum().sort_values("__date")
        if len(trend) > 1:
            fig = px.area(trend, x="__date", y="Total",
                          color_discrete_sequence=[color])
            fig.update_traces(fill="tozeroy",
                              line=dict(width=2.5, color=color),
                              fillcolor=color + "30")
            fig.update_layout(
                height=280, margin=dict(l=40, r=20, t=20, b=40),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(title=None, gridcolor="#e8ecf0"),
                yaxis=dict(title="Workload", gridcolor="#e8ecf0", rangemode="tozero"),
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Need 2+ date snapshots for trend.")

    with col_dist:
        st.markdown(f"### 🏢 {group_col} Distribution")
        sub_agg = (df_latest.groupby(group_col, as_index=False)["Total"]
                   .sum().sort_values("Total", ascending=False).head(12))
        if not sub_agg.empty:
            fig = px.bar(sub_agg, x=group_col, y="Total",
                         color="Total", color_continuous_scale=[[0, "#e3f2fd"], [1, color]],
                         text="Total")
            fig.update_traces(texttemplate="%{text:,}", textposition="outside",
                              marker_line_width=0)
            fig.update_layout(
                height=280, margin=dict(l=40, r=20, t=20, b=80),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(title=None, tickangle=35, gridcolor="#e8ecf0"),
                yaxis=dict(title=None, gridcolor="#e8ecf0",
                           range=[0, float(sub_agg["Total"].max()) * 1.18]),
                showlegend=False, coloraxis_showscale=False,
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No data.")


def render_heatmap(df_latest: pd.DataFrame, agenda: dict):
    cols = available_metric_cols(df_latest, agenda, "breakdown_columns", "total_columns")
    if not cols or df_latest.empty:
        return
    group_col = usable_group_col(df_latest, agenda)
    st.markdown(f"### 🔥 Heatmap — {group_col} × Metric Type")
    sub_list = df_latest[group_col].dropna().unique()[:15]
    rows = []
    for s in sub_list:
        sub_df = df_latest[df_latest[group_col] == s]
        r = {group_col: s}
        for c in cols:
            r[c] = float(sub_df[c].sum())
        rows.append(r)
    if not rows:
        return
    hmap = pd.DataFrame(rows).set_index(group_col)
    fig = px.imshow(hmap.T,
                    color_continuous_scale="YlOrRd",
                    aspect="auto",
                    text_auto=True)
    fig.update_layout(
        height=350, margin=dict(l=120, r=20, t=20, b=80),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        coloraxis_colorbar=dict(title="Count"),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_svamitva_kpis(df_latest: pd.DataFrame, df_prev: pd.DataFrame):
    metrics = [
        ("Ground Truthing Pending", "GROUND TRUTHING PENDING", "lower"),
        ("Map 2 Pending", "PENDING MAP 2", "lower"),
        ("Map 3 Finalised", "Map 3 Finalised", "higher"),
        ("Net Pending Workload", "Total", "lower"),
    ]
    cols = st.columns(4)
    has_prev = not df_prev.empty

    for idx, (label, col, direction) in enumerate(metrics):
        current = metric_sum(df_latest, col)
        previous = metric_sum(df_prev, col) if has_prev else None
        with cols[idx]:
            st.metric(
                label,
                fmt(current),
                delta=delta_label(current, previous),
                delta_color="inverse" if direction == "lower" else "normal",
            )

    if has_prev:
        st.caption("Compared with the previous snapshot. Green means pending work reduced or Map 3 finalisation increased.")
    else:
        st.caption("Add one more dated Svamitva snapshot to show comparison with the previous review.")


def render_svamitva_charts(df_all: pd.DataFrame, df_latest: pd.DataFrame, df_prev: pd.DataFrame, agenda: dict):
    group_col = usable_group_col(df_latest, agenda)
    stage_cols = ["GROUND TRUTHING PENDING", "PENDING MAP 2", "Map 3 Finalised"]
    available = [c for c in stage_cols if c in df_all.columns]

    col_trend, col_group = st.columns(2)

    with col_trend:
        st.markdown("### 📈 Stage Trend")
        trend_src = df_all.copy()
        trend_src["Snapshot"] = snapshot_label(trend_src)
        order = list(pd.unique(trend_src["Snapshot"]))
        trend = trend_src.groupby("Snapshot", as_index=False)[available].sum()
        trend["Snapshot"] = pd.Categorical(trend["Snapshot"], categories=order, ordered=True)
        trend = trend.sort_values("Snapshot")

        if len(trend) > 1:
            trend_long = trend.melt("Snapshot", value_vars=available, var_name="Stage", value_name="Count")
            fig = px.line(
                trend_long,
                x="Snapshot",
                y="Count",
                color="Stage",
                markers=True,
                color_discrete_map={
                    "GROUND TRUTHING PENDING": "#d62728",
                    "PENDING MAP 2": "#ff7f0e",
                    "Map 3 Finalised": "#2ca02c",
                },
            )
            fig.update_layout(
                height=310, margin=dict(l=40, r=20, t=20, b=70),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(title=None, gridcolor="#e8ecf0"),
                yaxis=dict(title="Count", gridcolor="#e8ecf0", rangemode="tozero"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Need 2+ Svamitva snapshots for trend comparison.")

    with col_group:
        st.markdown(f"### 🏢 Latest by {group_col}")
        group = (df_latest.groupby(group_col, as_index=False)[available]
                 .sum().sort_values("GROUND TRUTHING PENDING", ascending=False).head(12))
        if not group.empty:
            group_long = group.melt(group_col, value_vars=available, var_name="Stage", value_name="Count")
            fig = px.bar(
                group_long,
                x=group_col,
                y="Count",
                color="Stage",
                barmode="group",
                color_discrete_map={
                    "GROUND TRUTHING PENDING": "#d62728",
                    "PENDING MAP 2": "#ff7f0e",
                    "Map 3 Finalised": "#2ca02c",
                },
            )
            fig.update_layout(
                height=310, margin=dict(l=40, r=20, t=20, b=90),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(title=None, tickangle=35, gridcolor="#e8ecf0"),
                yaxis=dict(title="Count", gridcolor="#e8ecf0", rangemode="tozero"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No Svamitva stage data available.")

    if df_prev.empty:
        return

    st.markdown("### 🔁 Change Since Previous Snapshot")
    latest = df_latest.groupby(group_col, as_index=False)[available].sum()
    prev = df_prev.groupby(group_col, as_index=False)[available].sum()
    change = latest.merge(prev, on=group_col, how="outer", suffixes=("", " Previous")).fillna(0)
    change["Ground Truthing Change"] = change["GROUND TRUTHING PENDING"] - change["GROUND TRUTHING PENDING Previous"]
    change["Map 2 Change"] = change["PENDING MAP 2"] - change["PENDING MAP 2 Previous"]
    change["Map 3 Added"] = change["Map 3 Finalised"] - change["Map 3 Finalised Previous"]
    change["Net Pending Change"] = change["Ground Truthing Change"] + change["Map 2 Change"]

    display = change[[
        group_col,
        "GROUND TRUTHING PENDING",
        "Ground Truthing Change",
        "PENDING MAP 2",
        "Map 2 Change",
        "Map 3 Finalised",
        "Map 3 Added",
        "Net Pending Change",
    ]].sort_values(["Net Pending Change", "Map 3 Added"], ascending=[True, False])

    rename = {
        group_col: group_col,
        "GROUND TRUTHING PENDING": "GT Pending",
        "PENDING MAP 2": "Map 2 Pending",
        "Map 3 Finalised": "Map 3 Finalised Till Date",
    }
    st.dataframe(display.rename(columns=rename), hide_index=True, use_container_width=True, height=360)


def render_svamitva_lowest_progress(df_latest: pd.DataFrame, df_prev: pd.DataFrame):
    if df_prev.empty:
        st.info("Add one previous Svamitva snapshot to highlight lowest progress.")
        return

    sub_tehsil_col = "Tehsil/Sub Tehsil" if "Tehsil/Sub Tehsil" in df_latest.columns else "Sub-Tehsil"
    pending_metrics = [
        ("Ground Truthing", "GROUND TRUTHING PENDING"),
        ("Map 2", "PENDING MAP 2"),
    ]
    group_cols = [c for c in ["Sub Division", sub_tehsil_col, "Officer"] if c in df_latest.columns]
    if not group_cols:
        return

    def _rank_lowest_progress(metric_col: str) -> pd.DataFrame:
        latest = df_latest.groupby(group_cols, as_index=False)[metric_col].sum()
        prev = df_prev.groupby(group_cols, as_index=False)[metric_col].sum()
        merged = latest.merge(prev, on=group_cols, how="outer", suffixes=(" Current", " Previous")).fillna(0)
        current_col = f"{metric_col} Current"
        previous_col = f"{metric_col} Previous"
        merged["Progress"] = merged[previous_col] - merged[current_col]
        merged["Change"] = merged[current_col] - merged[previous_col]
        merged["Review Unit"] = merged[sub_tehsil_col].astype(str) + " | " + merged["Officer"].astype(str)
        if "Sub Division" in merged.columns:
            merged["Review Unit"] = merged["Sub Division"].astype(str) + " | " + merged["Review Unit"]
        return merged.sort_values(["Progress", current_col], ascending=[True, False]).head(5)

    st.markdown("### 🚦 Top 5 Lowest Progress")
    panels = []
    for label, metric_col in pending_metrics:
        ranked = _rank_lowest_progress(metric_col)
        current_col = f"{metric_col} Current"
        previous_col = f"{metric_col} Previous"
        cards = []

        for _, row in ranked.iterrows():
            previous = float(row.get(previous_col, 0) or 0)
            current = float(row.get(current_col, 0) or 0)
            progress = previous - current
            change = current - previous

            if progress < 0:
                status = "Worsened"
                status_class = "worsened"
            elif progress == 0:
                status = "No progress"
                status_class = "no-progress"
            else:
                status = "Low progress"
                status_class = "low-progress"

            officer = str(row.get("Officer", "Unknown officer")).strip() or "Unknown officer"
            sub_division = row.get("Sub Division", "")
            sub_tehsil = row.get(sub_tehsil_col, "")
            title_parts = [str(v).strip() for v in [sub_division, officer] if str(v).strip()]
            title = " - ".join(title_parts) if title_parts else officer
            meta_parts = [str(v).strip() for v in [sub_tehsil] if str(v).strip()]
            meta = " | ".join(meta_parts) if meta_parts else row.get("Review Unit", "")

            cards.append(
                f'<div class="officer-progress-tab">'
                f'<div class="officer-progress-tab-title">{esc(title)}</div>'
                f'<div class="officer-progress-meta">{esc(meta)}</div>'
                f'<div class="officer-progress-stats">'
                f'<div class="officer-progress-stat"><span>Previous</span><strong>{fmt(previous)}</strong></div>'
                f'<div class="officer-progress-stat"><span>Current</span><strong>{fmt(current)}</strong></div>'
                f'<div class="officer-progress-stat"><span>Net Change</span><strong>{change:+,.0f}</strong></div>'
                f'</div>'
                f'<div class="officer-progress-status {status_class}">{status}</div>'
                f'</div>'
            )

        cards_html = "".join(cards) or f"<p>No {esc(label)} comparison available.</p>"
        panels.append(
            f'<div class="lowest-progress-panel">'
            f'<h4>{esc(label)}</h4>'
            f'{cards_html}'
            f'</div>'
        )

    st.markdown(
        f"""<div class="lowest-progress-grid">{''.join(panels)}</div>""",
        unsafe_allow_html=True,
    )


def render_svamitva_officer_pendency(df_latest: pd.DataFrame):
    pending_cols = ["GROUND TRUTHING PENDING", "PENDING MAP 2"]
    sub_tehsil_col = "Tehsil/Sub Tehsil" if "Tehsil/Sub Tehsil" in df_latest.columns else "Sub-Tehsil"
    required_cols = ["Officer", sub_tehsil_col, *pending_cols]
    if not all(c in df_latest.columns for c in required_cols):
        return

    raw_roles = df_latest["Officer"].dropna().astype(str).str.strip().loc[lambda s: s.ne("")].unique()
    preferred_order = ["Tehsildar", "Naib Tehsildar"]
    officer_roles = [
        role for role in preferred_order if role in raw_roles
    ] + sorted(role for role in raw_roles if role not in preferred_order)
    if not officer_roles:
        st.info("No sub-tehsil and officer-wise Svamitva pendency found.")
        return

    labels = {
        "GROUND TRUTHING PENDING": "Ground Truthing Pending",
        "PENDING MAP 2": "Map 2 Pending",
    }
    for pending_col in pending_cols:
        st.markdown(f"### {labels[pending_col]}")
        for officer_role in officer_roles:
            role_df = df_latest[
                df_latest["Officer"].astype(str).str.strip() == officer_role
            ].copy()
            if role_df.empty:
                continue

            group_cols = [sub_tehsil_col]
            if "Sub Division" in role_df.columns:
                group_cols = ["Sub Division", sub_tehsil_col]

            pendency = role_df.groupby(group_cols, as_index=False)[pending_col].sum()
            pendency = pendency[pendency[pending_col] > 0].copy()
            if pendency.empty:
                st.caption(f"{labels[pending_col]} ({officer_role}): no pending cases.")
                continue

            pendency["Review Unit"] = pendency[sub_tehsil_col].astype(str)
            if "Sub Division" in pendency.columns:
                pendency["Review Unit"] = (
                    pendency["Sub Division"].astype(str) + " | " + pendency["Review Unit"]
                )
            pendency = pendency.sort_values(pending_col, ascending=False)
            max_pending = float(pendency[pending_col].max())
            pendency["Signal"] = pendency[pending_col].apply(
                lambda value: traffic_signal_color(float(value), max_pending)
            )
            pendency["Display Unit"] = pendency["Review Unit"].map(
                lambda value: "<br>".join(esc(part.strip()) for part in str(value).split("|"))
            )

            st.markdown(f"#### {labels[pending_col]} ({esc(officer_role)})")
            st.caption("Traffic signal: red = highest pendency, amber = medium, green = lower.")
            height = max(360, min(520, 26 * len(pendency) + 230))
            fig = px.bar(
                pendency,
                x="Display Unit",
                y=pending_col,
                text=pending_col,
                hover_data={"Review Unit": True, "Display Unit": False, pending_col: ":,"},
            )
            fig.update_traces(
                marker_color=pendency["Signal"],
                texttemplate="%{text:,}",
                textposition="outside",
                textfont=dict(color="#0a2240", size=13, family="Arial Black"),
                cliponaxis=False,
            )
            y_max = max_pending * 1.22 if max_pending else 1
            fig.update_layout(
                height=height, margin=dict(l=45, r=30, t=10, b=115),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(title=None, tickangle=0, categoryorder="array",
                           categoryarray=pendency["Display Unit"].tolist(), gridcolor="#e8ecf0",
                           tickfont=dict(color="#0a2240", size=12, family="Arial Black")),
                yaxis=dict(title="Pending cases", gridcolor="#e8ecf0", range=[0, y_max]),
                showlegend=False,
                bargap=0.28,
                uniformtext=dict(minsize=9, mode="hide"),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_top_officers(df_latest: pd.DataFrame, df_all: pd.DataFrame, agenda: dict):
    if "Officer" not in df_latest.columns or useful_nunique(df_latest, "Officer") == 0:
        return
    st.markdown("### 👤 Top 5 Officers by Pendency")
    top5 = df_latest.nlargest(5, "Total")
    color = agenda["color"]
    colors = [color + "ff", color + "cc", color + "aa", color + "88", color + "66"]
    group_col = usable_group_col(df_latest, agenda)

    for idx, (_, row) in enumerate(top5.iterrows()):
        officer = row.get("Officer", "Unknown")
        group_val = row.get(group_col, "Unknown")
        tehsil = row.get("Tehsil/Sub Tehsil", "N/A")
        total = int(row["Total"])
        grand = float(df_latest["Total"].sum()) or 1
        pct = total / grand * 100
        bar_color = colors[idx] if idx < 5 else colors[-1]

        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown(
                f"<p style='margin:0.2rem 0;font-size:0.9rem;font-weight:600;color:#0a2240'>"
                f"{esc(group_val)} › {esc(tehsil)} › {esc(officer)}</p>"
                f"<p style='margin:0;font-size:1rem;color:#333'>"
                f"<strong>{fmt(total)}</strong> "
                f"<span style='color:#90a4ae;font-size:0.82rem'>({pct:.1f}% of total)</span></p>",
                unsafe_allow_html=True,
            )
        with c2:
            # Trend sparkline
            mask = (
                (df_all["Officer"].astype(str) == str(officer)) &
                (df_all[group_col].astype(str) == str(group_val))
            )
            history = (df_all[mask]
                       .groupby("__date", as_index=False)["Total"]
                       .sum()
                       .sort_values("__date"))
            if len(history) > 1:
                fig = px.line(history, x="__date", y="Total", markers=True,
                              color_discrete_sequence=[bar_color])
                fig.update_traces(line=dict(width=2), marker=dict(size=5))
                fig.update_layout(
                    height=80, margin=dict(l=0, r=0, t=0, b=0),
                    showlegend=False,
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                )
                fig.update_xaxes(visible=False)
                fig.update_yaxes(visible=False, rangemode="tozero")
                st.plotly_chart(fig, use_container_width=True,
                                config={"displayModeBar": False})
            else:
                st.markdown(
                    f"<div style='height:1.2rem;background:{bar_color};border-radius:4px;"
                    f"width:{min(pct,100):.0f}%;margin-top:0.6rem'></div>",
                    unsafe_allow_html=True,
                )


def render_summary_table(df_latest: pd.DataFrame, agenda: dict):
    st.markdown("### 📋 Complete Summary Table")
    if df_latest.empty:
        st.info("No data.")
        return

    tbl = df_latest.copy()
    grand = float(tbl["Total"].sum()) or 1
    tbl["% of Total"] = (tbl["Total"] / grand * 100).round(2)
    tbl["Rank"] = tbl["Total"].rank(ascending=False, method="dense").astype(int)
    threshold = agenda["alert_threshold"]
    alert_col = agenda["target_col"] if agenda["target_col"] in tbl.columns else "Total"
    if agenda["target_type"] == "lower_better":
        tbl["Alert"] = tbl[alert_col].apply(lambda x: "⚠️" if x > threshold else "✅")
    else:
        tbl["Alert"] = tbl[alert_col].apply(lambda x: "⚠️" if x < threshold else "✅")

    # Column ordering
    id_candidates = ["Rank", *agenda.get("group_cols", []), "Sub Division",
                     "Tehsil/Sub Tehsil", "Sub-Tehsil", "District", "Officer"]
    id_cols = []
    for c in id_candidates:
        if c == "Rank" or (c in tbl.columns and useful_nunique(tbl, c) > 0):
            if c not in id_cols:
                id_cols.append(c)
    metric_cols = available_metric_cols(tbl, agenda, "columns")
    summary_cols = ["Total", "% of Total", "Alert"]
    display_cols = list(dict.fromkeys(id_cols + metric_cols + summary_cols))

    final = tbl[display_cols].sort_values("Total", ascending=False).reset_index(drop=True)

    # Format
    disp = final.copy()
    for c in metric_cols + ["Total"]:
        disp[c] = disp[c].apply(fmt)
    disp["% of Total"] = disp["% of Total"].apply(lambda x: f"{x:.1f}%")

    # Abbreviations
    abbr = {
        "Uncontested Pendency": "Uncontested",
        "Income Certificate": "Income Cert",
        "Copying Service": "Copying",
        "Inspection Records": "Inspection",
        "Overdue Mortgage": "Mortgage",
        "Overdue Court Orders": "Court Orders",
        "Overdue Fardbadars": "Fardbadars",
        "Tehsil/Sub Tehsil": "Tehsil",
        "% of Total": "%",
        "Pending Incorporation": "Pending Inc.",
        "Pending Digitisation": "Pending Dig.",
        "Property Cards Issued": "Cards Issued",
        "Pending Cards": "Pending Cards",
        "Pending Survey": "Pending Survey",
        "Pending Approval": "Pending Appr.",
        "Pending Attestation": "Pending Att.",
    }
    disp = disp.rename(columns=abbr)

    st.dataframe(disp, hide_index=True, use_container_width=True, height=400)

    # Export
    csv = final.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download CSV",
        data=csv,
        file_name=f"{agenda['key']}_summary.csv",
        mime="text/csv",
    )


def render_top3_subdivisions(df_latest: pd.DataFrame, df_prev: pd.DataFrame, agenda: dict):
    color = agenda["color"]
    group_col = usable_group_col(df_latest, agenda)
    agg = (df_latest.groupby(group_col, as_index=False)["Total"]
           .sum().sort_values("Total", ascending=False).head(3).reset_index(drop=True))
    medal = ["🥇", "🥈", "🥉"]
    bar_colors = [color + "ff", color + "aa", color + "66"]

    for i, row in agg.iterrows():
        sub = row[group_col]
        val = int(row["Total"])
        pct = val / float(df_latest["Total"].sum() or 1) * 100
        prev_val = 0
        if not df_prev.empty and group_col in df_prev.columns:
            prev_row = df_prev[df_prev[group_col] == sub]
            prev_val = int(prev_row["Total"].sum()) if not prev_row.empty else 0
        chg = pct_change(val, prev_val)

        c1, c2 = st.columns([3, 2])
        with c1:
            chg_color = "#e53935" if chg > 0 else "#43a047"
            chg_str = f"<span style='color:{chg_color};font-size:0.8rem'>{trend_icon(chg)} {chg:+.1f}%</span>" if prev_val else ""
            st.markdown(
                f"<p style='margin:0.2rem 0;font-size:0.95rem;font-weight:700;color:#0a2240'>"
                f"{medal[i]} {esc(sub)}</p>"
                f"<p style='margin:0;font-size:1rem;color:#333'>"
                f"<strong>{fmt(val)}</strong> "
                f"<span style='color:#90a4ae;font-size:0.82rem'>({pct:.1f}%)</span> {chg_str}</p>",
                unsafe_allow_html=True,
            )
        with c2:
            bar_w = min(pct / 40, 1.0) * 100
            st.markdown(
                f"<div style='height:1.4rem;background:{bar_colors[i]};border-radius:5px;"
                f"width:{bar_w:.0f}%;margin-top:0.6rem'></div>",
                unsafe_allow_html=True,
            )


# ─────────────────────────────── main tab renderer ──────────────────────────

def render_agenda_tab(agenda: dict):
    render_agenda_header(agenda)

    # ── Load data ──
    with st.spinner(f"Loading {agenda['label']} data…"):
        df_all = load_agenda(agenda["key"], cache_ver=st.session_state.get("cache_ver", "v1"))

    if df_all.empty:
        render_no_data(agenda)
        return

    # ── In-tab filters (avoid sidebar duplication across tabs) ──
    st.markdown("### Filters")
    fcol1, fcol2 = st.columns([2, 3])
    dates_available = df_all["__date"].dropna().unique()
    group_col = usable_group_col(df_all, agenda)
    with fcol1:
        if len(dates_available) >= 2:
            min_d, max_d = pd.to_datetime(dates_available.min()), pd.to_datetime(dates_available.max())
            dr = st.date_input(
                "Date range",
                value=(min_d.date(), max_d.date()),
                min_value=min_d.date(),
                max_value=max_d.date(),
                key=f"dr_{agenda['key']}",
            )
        else:
            dr = None
            st.caption("Date filter is available when at least 2 dated snapshots are found.")

    with fcol2:
        group_opts = sorted(df_all[group_col].dropna().unique().astype(str))
        selected_group = st.selectbox(group_col, ["All", *group_opts], key=f"group_single_{agenda['key']}")

    # ── Apply filters ──
    df = df_all.copy()
    if dr and len(dr) == 2:
        df = df[(df["__date"] >= pd.to_datetime(dr[0])) & (df["__date"] <= pd.to_datetime(dr[1]))]
    if selected_group != "All":
        df = df[df[group_col].astype(str) == selected_group]

    latest_date = df["__date"].max()
    if pd.notna(latest_date):
        df_latest = df[df["__date"] == latest_date].copy()
        prev_dates = df[df["__date"] < latest_date]["__date"].unique()
        df_prev = df[df["__date"] == prev_dates.max()].copy() if len(prev_dates) > 0 else pd.DataFrame()
    else:
        # Fallback for files without YYYYMMDD in filename: use most recently loaded source file.
        source_order = list(pd.unique(df["__source"].dropna()))
        if source_order:
            latest_source = source_order[-1]
            prev_source = source_order[-2] if len(source_order) > 1 else None
            df_latest = df[df["__source"] == latest_source].copy()
            df_prev = df[df["__source"] == prev_source].copy() if prev_source else pd.DataFrame()
        else:
            df_latest = pd.DataFrame()
            df_prev = pd.DataFrame()

    if df_latest.empty:
        st.warning("No data for selected filters.")
        return

    # ── Date badge ──
    if pd.notna(latest_date):
        st.caption(f"📅 Showing data as of **{pd.to_datetime(latest_date).strftime('%d %B %Y')}**")
    else:
        src = df_latest["__source"].iloc[0] if not df_latest.empty else "unknown file"
        st.caption(f"📄 Showing latest file snapshot: **{src}** (no YYYYMMDD date found in filename)")

    if agenda["key"] == "svamitva":
        st.markdown("## Key Metrics")
        render_svamitva_kpis(df_latest, df_prev)

        st.markdown("## Stage Analysis")
        render_svamitva_charts(df, df_latest, df_prev, agenda)

        st.markdown("## Lowest Progress")
        render_svamitva_lowest_progress(df_latest, df_prev)

        st.markdown("## Officer-wise Pendency")
        render_svamitva_officer_pendency(df_latest)

        st.markdown("## Full Data Table")
        render_summary_table(df_latest, agenda)
        return

    # ── KPI row ──
    st.markdown("## Key Metrics")
    render_kpi_row(df_latest, df_prev, agenda)

    # ── Pendency breakdown ──
    if agenda["columns"]:
        st.markdown("## Workload Breakdown")
        render_pendency_breakdown(df_latest, agenda)

    # ── Charts row ──
    st.markdown("## Visual Overview")
    render_charts(df, df_latest, agenda)

    # ── Heatmap ──
    if len(agenda["columns"]) > 1:
        render_heatmap(df_latest, agenda)

    # ── Insights row ──
    st.markdown("## Detailed Insights")
    col_left, col_right = st.columns([1, 1])
    with col_left:
        st.markdown(f"### 🏆 Top 3 {usable_group_col(df_latest, agenda)}")
        render_top3_subdivisions(df_latest, df_prev, agenda)
    with col_right:
        if "Officer" in df_latest.columns:
            render_top_officers(df_latest, df, agenda)

    # ── Summary table ──
    st.markdown("## Full Data Table")
    render_summary_table(df_latest, agenda)


# ─────────────────────────────── entry point ────────────────────────────────

def main():
    inject_css()

    # ── Header ──
    today_str = current_app_time_label()
    hcol1, hcol2 = st.columns([5, 1])
    with hcol1:
        st.markdown(f"""
        <div class="dash-header">
            <div>
                <h1>🏛️ Ludhiana District Revenue Dashboard</h1>
                <p class="subtitle">DC Review Tool — Mutations · E-seva · Svamitva · Tatima · Cadastral · Jamabandi</p>
            </div>
            <div class="header-badge">🕐 {today_str}</div>
        </div>
        """, unsafe_allow_html=True)
    with hcol2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Refresh All", key="global_refresh"):
            load_agenda.clear()
            v = st.session_state.get("cache_ver", "v1")
            num = int(v.replace("v", "")) + 1 if v.replace("v", "").isdigit() else 1
            st.session_state["cache_ver"] = f"v{num}"
            st.rerun()

    # ── Tabs ──
    tab_labels = [f"{a['icon']} {a['label']}" for a in AGENDAS]
    tabs = st.tabs(tab_labels)

    for tab, agenda in zip(tabs, AGENDAS):
        with tab:
            render_agenda_tab(agenda)

    # ── Footer ──
    st.markdown("""
    <div class="dash-footer">
        <div>Ludhiana District Administration &nbsp;|&nbsp; Revenue Dashboard v2.0</div>
        <div>Developed by <strong style='color:#1a4b8c'>Shivam Gulati</strong>, Land Revenue Fellow
        &nbsp;·&nbsp; <a href='mailto:Shivamgulati137@gmail.com' style='color:#1a4b8c'>Shivamgulati137@gmail.com</a>
        &nbsp;·&nbsp; 62844-12362</div>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()

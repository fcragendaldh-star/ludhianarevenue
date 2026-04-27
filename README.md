# 🏛️ Ludhiana District Revenue Dashboard

**DC Review Tool** — Multi-agenda pendency & progress monitoring dashboard  
Developed by **Shivam Gulati**, Land Revenue Fellow

---

## Current Agendas

| Tab | Agenda | Folder Secret Key |
|-----|--------|------------------|
| ⚖️ | Uncontested Mutations & E-seva | `AGENDA_FCR_FOLDER_ID` |
| 🏡 | Svamitva | `AGENDA_SVAMITVA_FOLDER_ID` |
| 📐 | Tatima Incorporation | `AGENDA_TATIMA_FOLDER_ID` |
| 🗺️ | Cadastral Digitisation | `AGENDA_CADASTRAL_FOLDER_ID` |
| 📋 | Live Jamabandi | `AGENDA_JAMABANDI_FOLDER_ID` |

---

## Setup

### 1. Google Drive

For each agenda, create a dedicated folder in Google Drive:
- Upload daily Excel snapshots named with date suffix: `FCR_20251104.xlsx`
- Share the folder with your service account email (Editor access)
- Copy the folder ID from the URL

### 2. Secrets

Copy `.streamlit/secrets.toml.template` → `.streamlit/secrets.toml` and fill in:
- `GOOGLE_APPLICATION_CREDENTIALS_JSON` — your service account JSON
- One `AGENDA_<KEY>_FOLDER_ID` per agenda

On **Streamlit Cloud**, paste each key-value in Settings → Secrets.

### 3. Excel File Format

Each daily file must contain at minimum:
- At least one grouping column from the agenda's `group_cols`
- Metric columns as defined in `agenda_config.py` for that agenda

Date is parsed from filename (`YYYYMMDD` pattern). Files without a date are still loaded but won't appear in trend charts.

### 4. Local Testing

Place `.xlsx` files in `data/<agenda_key>/` (e.g. `data/fcr/`, `data/svamitva/`).  
The dashboard will use local files when Drive is not configured.

---

## Adding a New Agenda

Edit `agenda_config.py` — add an entry to `AGENDAS` list with:
```python
{
    "key": "my_agenda",
    "label": "My Agenda",
    "icon": "📊",
    "description": "Short description",
    "folder_secret": "AGENDA_MY_AGENDA_FOLDER_ID",
    "columns": ["Col A", "Col B", "Col C"],
    "total_columns": ["Col A", "Col B"],  # comparable pending/workload columns only
    "breakdown_columns": ["Col A", "Col B"],
    "group_cols": ["Sub Division", "Officer"],
    "group_label": "Sub Division",
    "target_col": "Col A",
    "target_type": "lower_better",   # or "higher_better"
    "alert_threshold": 30,
    "color": "#e91e63",
}
```
Then add `AGENDA_MY_AGENDA_FOLDER_ID` to secrets.

---

## Run Locally

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

If port `8501` is busy:
```bash
python -m streamlit run app.py --server.port 8502
```

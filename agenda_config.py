"""
agenda_config.py — Central configuration for all dashboard agendas.

Each agenda entry defines:
  key          : short machine-readable identifier (used in secrets keys)
  label        : display name shown on the tab
  icon         : emoji icon for the tab
  description  : one-line description shown on the tab header
  folder_secret: the Streamlit secrets key that holds the Google Drive folder ID
                 (set AGENDA_<KEY>_FOLDER_ID in .streamlit/secrets.toml)
  folder_name  : name of the local data folder (defaults to key if not specified)
  columns      : list of metric columns expected in the Excel sheet
  total_columns: columns that should be summed into the dashboard Total KPI
                 (keep this to comparable pending/workload columns only)
  group_cols   : columns used to identify a unique row (for grouping / display)
  target_col   : the primary KPI column (used for top-level metrics & alerts)
  target_type  : "lower_better" (pendency) or "higher_better" (completion %)
  alert_threshold : value above/below which an alert is raised (depends on target_type)
  color        : accent color used for charts on this tab
"""

AGENDAS = [
    # ----------------------------------------- Uncontested Mutations & E-seva
    {
        "key": "fcr",
        "label": "Uncontested Mutations & E-seva",
        "icon": "⚖️",
        "description": "Daily pendency across Uncontested Mutations and E-seva records",
        "folder_secret": "AGENDA_FCR_FOLDER_ID",
        "folder_name": "uncontesed mutations",
        "columns": [
            "Uncontested Pendency",
            "Income Certificate",
            "Copying Service",
            "Inspection Records",
            "Overdue Mortgage",
            "Overdue Court Orders",
            "Overdue Fardbadars",
        ],
        "group_cols": ["Sub Division", "Tehsil/Sub Tehsil", "Officer"],
        "total_columns": [
            "Uncontested Pendency",
            "Income Certificate",
            "Copying Service",
            "Inspection Records",
            "Overdue Mortgage",
            "Overdue Court Orders",
            "Overdue Fardbadars",
        ],
        "group_label": "Sub Division",
        "target_col": "Total",
        "target_type": "lower_better",
        "alert_threshold": 50,
        "color": "#1f77b4",
    },
    # ------------------------------------------------------------ Svamitva
    {
        "key": "svamitva",
        "label": "Svamitva",
        "icon": "🏡",
        "description": "",
        "folder_secret": "AGENDA_SVAMITVA_FOLDER_ID",
        "folder_id": "1IuqoL6mkvmPN_6uiUwOLYElnC72s_e5R",
        "columns": [
            "GROUND TRUTHING PENDING",
            "PENDING MAP 2",
            "Map 3 Finalised",
        ],
        "group_cols": ["Sub Division", "Sub-Tehsil", "Officer"],
        "total_columns": [
            "GROUND TRUTHING PENDING",
            "PENDING MAP 2",
        ],
        "breakdown_columns": [
            "GROUND TRUTHING PENDING",
            "PENDING MAP 2",
        ],
        "group_label": "Sub Division",
        "target_col": "GROUND TRUTHING PENDING",
        "target_type": "lower_better",
        "alert_threshold": 20,
        "color": "#2ca02c",
    },
    # ------------------------------------------------- Tatima Incorporation
    {
        "key": "tatima",
        "label": "Tatima Incorporation",
        "icon": "📐",
        "description": "Status of Tatima (field measurement) incorporation in revenue records",
        "folder_secret": "AGENDA_TATIMA_FOLDER_ID",
        "folder_id": "1HlBVtjgGGXbv_HGcrx85YqReQH-yU7d3",
        "columns": [
            "Total No of Villages",
            "No. of Villages where the work is in progress",
            "No. of Villages where work has not started",
            "Total Tatima Incorporated",
            "Villages where work is done",
        ],
        "group_cols": ["Sub-Tehsil", "Officer"],
        "total_columns": [
            "No. of Villages where the work is in progress",
            "No. of Villages where work has not started",
        ],
        "breakdown_columns": [
            "No. of Villages where the work is in progress",
            "No. of Villages where work has not started",
        ],
        "group_label": "Tehsil/Sub Tehsil",
        "target_col": "No. of Villages where work has not started",
        "target_type": "lower_better",
        "alert_threshold": 30,
        "color": "#ff7f0e",
    },
    # -------------------------------------- Digitisation of Cadastral Maps
    {
        "key": "cadastral",
        "label": "Cadastral Digitisation",
        "icon": "🗺️",
        "description": "Progress of cadastral (field map) digitisation across tehsils",
        "folder_secret": "AGENDA_CADASTRAL_FOLDER_ID",
        "columns": [
            "No. of villages mussavis validated by patwari         (1st level)",
            "No. of villages Final validated at  CRO level",
            "Villages pending for 1st Level Validation at Patwari Level",
            "Pending Villages Record Required PRSC for Error Correction Patwari level  (P2)",
            "Total Villages pending for validation & Correction by Patwari   (P1+P2)      (A)",
            "Pending villages at PRSC LEVEL for error corrections   (B)",
            "Villages Pending at CRO Level C",
            "Total Mussavi Validation Pendency   (A+B+C)",
        ],
        "group_cols": ["Sub-Tehsil", "Officer"],
        "total_columns": [
            "Total Mussavi Validation Pendency   (A+B+C)",
        ],
        "breakdown_columns": [
            "Villages pending for 1st Level Validation at Patwari Level",
            "Pending Villages Record Required PRSC for Error Correction Patwari level  (P2)",
            "Pending villages at PRSC LEVEL for error corrections   (B)",
            "Villages Pending at CRO Level C",
        ],
        "group_label": "Tehsil/Sub Tehsil",
        "target_col": "Total Mussavi Validation Pendency   (A+B+C)",
        "target_type": "lower_better",
        "alert_threshold": 50,
        "color": "#9467bd",
    },
    # ----------------------------------------------- Status of Live Jamabandi
    {
        "key": "jamabandi",
        "label": "Live Jamabandi",
        "icon": "📋",
        "description": "Live Jamabandi (land record) status — approvals, attestations & pendency",
        "folder_secret": "AGENDA_JAMABANDI_FOLDER_ID",
        "columns": [
            "Total Computerised Jamabandis to be prepared",
            "Total no of Computerised Jamabandis prepared Till Date",
            "Total no of Jamabandis printed by BOOT operator",
            "Validated By Patwari",
            "Validated By Kanungo",
            "Validated By CRO",
            "Deposited in Sadar Record Room",
            "Total Pending To be deposited in sadar",
            "Total Live of Jamabndis",
            "Total  Jamabandis consigned but Pending to Live",
        ],
        "group_cols": ["District", "Tehsil/Sub Tehsil"],
        "total_columns": [
            "Total Pending To be deposited in sadar",
            "Total  Jamabandis consigned but Pending to Live",
        ],
        "breakdown_columns": [
            "Total Pending To be deposited in sadar",
            "Total  Jamabandis consigned but Pending to Live",
        ],
        "group_label": "Tehsil/Sub Tehsil",
        "target_col": "Total Pending To be deposited in sadar",
        "target_type": "lower_better",
        "alert_threshold": 40,
        "color": "#d62728",
    },
]

# Quick lookup by key
AGENDA_MAP = {a["key"]: a for a in AGENDAS}

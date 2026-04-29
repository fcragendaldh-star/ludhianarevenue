"""
Google Drive Storage Integration Module
Handles file operations with Google Drive — supports per-agenda folder IDs.
"""

import os
import logging
from typing import List, Optional
from io import BytesIO
import json

logger = logging.getLogger(__name__)


class GoogleDriveStorage:
    """Google Drive Storage — connects to a single folder by ID."""

    def __init__(self, folder_id: str, credentials_json: str):
        self.folder_id = folder_id
        self.credentials_json = credentials_json

        if not self.folder_id:
            raise ValueError("folder_id is required")
        if not self.credentials_json:
            raise ValueError("credentials_json is required")

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaIoBaseDownload
            from googleapiclient.errors import HttpError

            if isinstance(self.credentials_json, str):
                creds_dict = json.loads(self.credentials_json)
            else:
                creds_dict = self.credentials_json

            credentials = service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=["https://www.googleapis.com/auth/drive.readonly"],
            )
            self.drive_service = build("drive", "v3", credentials=credentials)
            self.MediaIoBaseDownload = MediaIoBaseDownload
            self.HttpError = HttpError
            logger.info(f"✓ Google Drive initialised for folder: {self.folder_id[:20]}...")
        except ImportError:
            raise ImportError(
                "google-api-python-client and google-auth are required. "
                "Install with: pip install google-api-python-client google-auth"
            )

    def list_files(self) -> List[dict]:
        """List Excel-compatible files in the configured folder."""
        try:
            query = (
                f"'{self.folder_id}' in parents and "
                "(mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' "
                "or mimeType='application/vnd.ms-excel' "
                "or mimeType='application/vnd.google-apps.spreadsheet') and trashed=false"
            )
            results = self.drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType, createdTime, modifiedTime)",
                orderBy="modifiedTime desc",
            ).execute()
            files = results.get("files", [])
            logger.info(f"Found {len(files)} Excel-compatible files in folder {self.folder_id[:12]}...")
            return files
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return []

    def download_file(self, file_id: str, mime_type: str = "") -> BytesIO:
        """Download a file by its Drive ID."""
        try:
            if mime_type == "application/vnd.google-apps.spreadsheet":
                request = self.drive_service.files().export_media(
                    fileId=file_id,
                    mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                request = self.drive_service.files().get_media(fileId=file_id)
            buf = BytesIO()
            downloader = self.MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            buf.seek(0)
            return buf
        except Exception as e:
            logger.error(f"Error downloading file {file_id}: {e}")
            return BytesIO()

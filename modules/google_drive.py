import config

from typing import Optional
from googleapiclient import discovery, http
from oauth2client.service_account import ServiceAccountCredentials
from io import BytesIO


class Drive:
    """
    Class for connecting the bot to google drive and uploading files.
    This is meant for uploading channel archives and logs.

    Currently only supports logging in/authenticating with a service account.

    Attributes
    ---------------
    credentials: :class:`auth2client.service_account.ServiceAccountCredentials`
        The service account client created from the service account file.
    drive_service: :class:`googleapiclient.discovery.Resource`
        service resource built with :attr:`credentials`.
    """

    def __init__(self):
        self.credentials = ServiceAccountCredentials.from_json_keyfile_name(
            config.SERVICE_ACCOUNT_FILE
        )
        self.drive_service = discovery.build(
            "drive", "v3", credentials=self.credentials
        )
        self.sheet_service = discovery.build(
            "sheets", "v4", credentials=self.credentials
        )

    def download_spreadsheet(self, spreadsheet_id: str) -> dict[str, list[list[str]]]:
        """
        Download a spreadsheet with all the worksheets in it

        Parameters
        ----------------
        spreadsheet_id: :class:`str`
            ID of the spreadsheet.

        Returns
        -------
        :class:`dict`
            Returns dict with all the values of the spreadsheet in it.
        """
        # gather titles so they can be used in getting values
        data = (
            self.sheet_service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id)
            .execute()
        )
        sheet_titles = [sheet["properties"]["title"] for sheet in data["sheets"]]

        results = {}
        for sheet_title in sheet_titles:
            values = (
                self.sheet_service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=f"{sheet_title}!A1:n")
                .execute()
            )
            results[sheet_title] = values["values"]

        return results

    def get_or_create_folder(self, folder_name: str) -> Optional[str]:
        """
        A function for either getting or creating a folder in the google drive folder config.DRIVE_PARENT_FOLDER_ID

        Parameters
        ----------------
        folder_name: :class:`str`
            Name of the requested folder.

        Returns
        -------
        :class:`str`
            Id of the requested folder if possible, returns `None` if an error occurs.
        """
        # search for folder name
        query = f'name="{folder_name}" and trashed!=true and mimeType="application/vnd.google-apps.folder"'

        folders = self.drive_service.files().list(q=query).execute()
        items = folders.get("files", [])
        if items:
            folder_id = items[0]["id"]
        else:
            body = {
                "name": folder_name,
                "parents": [config.DRIVE_PARENT_FOLDER_ID],
                "mimeType": "application/vnd.google-apps.folder",
            }
            request = self.drive_service.files().create(body=body).execute()
            folder_id = request["id"]

        return folder_id

    def download_file(self, file_id: str):
        """
        Download a file from google drive by its id.

        Parameters
        ----------
        file_id: :class:`str`
            ID of the file.

        Returns
        -------
        :class:``
            Downloaded file.

        """

    def upload(self, data: str, file_name: str, parent_folder: str = None) -> str:
        """
        A function for uploading files to google drive

        Parameters
        ----------------
        data: :class:`str`
            Text that will be the data of the file.
        file_name: :class:`str`
            Name of the file that will be uploaded.
        parent_folder: Optional[:class:`str`]
            Optional argument to put the file in a certain folder.
            Argument needs to be folder name, not id.

        Returns
        -------
        :class:`str`
            Link to the uploaded file if uploaded was successful, if not, returns empty string.
        """
        # convert given data into uploadable file
        media = http.MediaIoBaseUpload(
            BytesIO(data.encode()), mimetype="text/plain", resumable=True
        )

        body = {"name": file_name, "mimeType": "application/vnd.google-apps.document"}
        if parent_folder:
            folder_id = self.get_or_create_folder(parent_folder)
            if folder_id:
                body["parents"] = [folder_id]

        request = self.drive_service.files().create(body=body, media_body=media)

        status, response = request.next_chunk()
        return (
            f'https://docs.google.com/document/d/{response["id"]}' if response else ""
        )

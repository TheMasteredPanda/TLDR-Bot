import config

from apiclient import discovery, http
from oauth2client.service_account import ServiceAccountCredentials
from io import BytesIO


class Drive:
    def __init__(self):
        self.credentials = ServiceAccountCredentials.from_json_keyfile_name(config.SERVICE_ACCOUNT_FILE)
        self.service = discovery.build('drive', 'v3', credentials=self.credentials)

    def get_or_create_folder(self, folder_name):
        # search for folder name
        query = f'name="{folder_name}" and trashed!=true and mimeType="application/vnd.google-apps.folder"'
        try:
            folders = self.service.files().list(q=query).execute()
            items = folders.get('files', [])
            if items:
                folder_id = items[0]['id']
            else:
                body = {
                    "name": folder_name,
                    "parents": [config.DRIVE_PARENT_FOLDER_ID],
                    "mimeType": "application/vnd.google-apps.folder"
                }
                request = self.service.files().create(body=body).execute()
                folder_id = request['id']
        except:
            return None

        return folder_id

    def upload(self, data: str, file_name: str, parent_folder: str = None):
        # convert given data into uploadable file
        media = http.MediaIoBaseUpload(BytesIO(data.encode()), mimetype='text/plain', resumable=True)

        body = {
            'name': file_name,
            'mimeType': 'application/vnd.google-apps.document'
        }
        if parent_folder:
            folder_id = self.get_or_create_folder(parent_folder)
            if folder_id:
                body['parents'] = [folder_id]

        request = self.service.files().create(
            body=body,
            media_body=media
        )

        status, response = request.next_chunk()
        return f'https://docs.google.com/document/d/{response["id"]}' if response else ''

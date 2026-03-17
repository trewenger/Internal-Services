To use the google integration, you need to supply a credentials.json file 
in this directory. Documentation can be found here: https://developers.google.com/workspace/guides/create-credentials

In the .env loaded by the script importing the GoogleSession, include 
GOOGLE_SERVICE_SCOPES (1 or more, though the class is only configured to handle 'https://www.googleapis.com/auth/spreadsheets' at this time), 
and GOOGLE_CREDENTIALS_PATH (path to the credentials.json).

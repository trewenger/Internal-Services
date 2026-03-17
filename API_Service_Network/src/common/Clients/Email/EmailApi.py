"""
Docstring for Common.clients.email.EmailApi
Purpose: 
-   This client is used to send emails via the send_email() function. 
-   Utilizes SMTP2Go REST API's POST request.
-   Common/clients/fishbowl/FishbowlCalls.py
"""

import requests, json, base64, os

def send_email(subject: str, html_body: str, recipients: list, attachments=[], sender="") -> None:
    """ 
    -   The sent emails require a subject, html body, and a list of recipients. 
    -   Attachments are optional and represent a list of file paths. They are automatically converted to base64
        encoded attachments. 
    -   sender is also an optional field, but allows you to configure the sent from address. 
    -   The body can consist of any valid HTML, allowing for deeper customization of the email content and style. 
    """
    sender = os.getenv('SENDER_EMAIL') if not sender else sender

    # .env configs
    SMTP2GO_API_KEY = os.getenv("SMTP2GO_API_KEY")

    payload = {
        "sender": sender,
        "to": recipients,
        "subject": subject,
        "html_body": html_body
    }
    url = "https://api.smtp2go.com/v3/email/send"
    headers = {
    'Content-Type': 'application/json',
    'url': 'https://api.smtp2go.com/v3/',
    'X-Smtp2go-Api-Key': SMTP2GO_API_KEY
    }

    # Convert file paths to base64-encoded attachments
    if attachments and len(attachments) > 0:
        encoded_attachments = []
        for filepath in attachments:
            with open(filepath, "rb") as f:
                file_data = f.read()
                encoded_attachments.append({
                    "filename": os.path.basename(filepath),
                    "fileblob": base64.b64encode(file_data).decode("utf-8")
                })
        payload["attachments"] = encoded_attachments


    payload = json.dumps(payload)

    response = requests.request("POST", url, headers=headers, data=payload)
    response_json = response.json()
    return {"status": response.status_code, 'data': response_json['data']}  # invite users needs this format

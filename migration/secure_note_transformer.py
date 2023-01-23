import logging
import subprocess
import json
from dataclasses import dataclass

import utils


@dataclass
class LPassData:
    url: str
    username: str
    password: str
    otp_secret: str
    notes: str
    title: str
    vault: str


class SecureNoteTransformer:
    def __init__(self, lpass_raw_data: LPassData):
        self.lpass_raw_data = lpass_raw_data

    def transform(self):
        template = None
        parsed_data = self._parse()
        if not parsed_data:
            return

        # Create Secure Note template
        if isinstance(parsed_data, LPassData):
            template = fetch_template("Secure Note")
            self._map_secure_note(parsed_data, template)
            return template

        note_type = parsed_data["NoteType"]
        if note_type == "Credit Card":
            template = fetch_template("Credit Card")
            self._map_credit_card(parsed_data, template)
            return template
        elif note_type == "Bank Account":
            template = fetch_template("Bank Account")
            self._map_bank_account(parsed_data, template)
            return template

        if not template:
            return

    def _parse(self):
        try:
            if not self.lpass_raw_data.notes.startswith("NoteType:"):
                return self.lpass_raw_data

            parsed_data = {}
            entries = self.lpass_raw_data.notes.split("\n")
            for row in entries:
                [key, value] = row.split(":")
                parsed_data[key] = value
            return parsed_data
        except:
            pass  # silence error here but prints in the vault_item_import.py

    def _map_secure_note(self, data: LPassData, template):
        template["title"] = data.title
        template["fields"] = [
            {
                "id": "notesPlain",
                "type": "STRING",
                "purpose": "NOTES",
                "label": "notesPlain",
                "value": data.notes
            }
        ]

    def _map_credit_card(self, data, template):
        template["title"] = self.lpass_raw_data.title
        template["fields"] = [
            {
                "id": "notesPlain",
                "type": "STRING",
                "purpose": "NOTES",
                "label": "notesPlain",
                "value": data["Notes"]
            },
            {
                "id": "cardholder",
                "type": "STRING",
                "label": "cardholder name",
                "value": data["Name on Card"]
            },
            {
                "id": "type",
                "type": "CREDIT_CARD_TYPE",
                "label": "type",
                "value": data["Type"]
            },
            {
                "id": "ccnum",
                "type": "CREDIT_CARD_NUMBER",
                "label": "number",
                "value": data["Number"]
            },
            {
                "id": "cvv",
                "type": "CONCEALED",
                "label": "verification number",
                "value": data["Security Code"]
            },
            {
                "id": "expiry",
                "type": "MONTH_YEAR",
                "label": "expiry date",
                "value": utils.lpass_date_to_1password_format(data["Expiration Date"])
            },
            {
                "id": "validFrom",
                "type": "MONTH_YEAR",
                "label": "valid from",
                "value": utils.lpass_date_to_1password_format(data["Start Date"])
            },
        ]

    def _map_bank_account(self, data, template):
        template["title"] = self.lpass_raw_data.title
        template["fields"] = [
            {
                "id": "notesPlain",
                "type": "STRING",
                "purpose": "NOTES",
                "label": "notesPlain",
                "value": data["Notes"]
            },
            {
                "id": "bankName",
                "type": "STRING",
                "label": "bank name",
                "value": data["Bank Name"]
            },
            {
                "id": "accountType",
                "type": "MENU",
                "label": "type",
                "value": data["Account Type"]
            },
            {
                "id": "routingNo",
                "type": "STRING",
                "label": "routing number",
                "value": data["Routing Number"]
            },
            {
                "id": "accountNo",
                "type": "STRING",
                "label": "account number",
                "value": data["Account Number"]
            },
            {
                "id": "swift",
                "type": "STRING",
                "label": "SWIFT",
                "value": data["SWIFT Code"]
            },
            {
                "id": "iban",
                "type": "STRING",
                "label": "IBAN",
                "value": data["IBAN Number"]
            },
            {
                "id": "telephonePin",
                "type": "CONCEALED",
                "label": "PIN",
                "value": data["Pin"]
            },
            {
                "id": "branchPhone",
                "section": {
                    "id": "branchInfo",
                    "label": "Branch Information"
                },
                "type": "PHONE",
                "label": "phone",
                "value": data["Branch Phone"]
            },
            {
                "id": "branchAddress",
                "section": {
                    "id": "branchInfo",
                    "label": "Branch Information"
                },
                "type": "STRING",
                "label": "address",
                "value": data["Branch Address"]
            }
        ]


def fetch_template(item_type: str):
    try:
        template = subprocess.run([
            "op", "item", "template", "get", item_type,
            "--format=json"
        ], check=True, capture_output=True)
        return json.loads(template.stdout)
    except:
        logging.warning(f"An error occurred when attempting to fetch the {item_type} item template.")

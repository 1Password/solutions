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
        parsed_data = self._parse()
        note_type = parsed_data["NoteType"]

        template = None
        if not note_type:
            pass
        elif note_type == "Credit Card":
            template = fetch_template("Credit Card")
            self._map_credit_card(parsed_data, template)
            return template

        if not template:
            return

    def _parse(self):
        parsed_data = {}
        entries = self.lpass_raw_data.notes.split("\n")
        for row in entries:
            [key, value] = row.split(":")
            parsed_data[key] = value
        return parsed_data

    def _map_credit_card(self, data, template):
        template["title"] = data["Name on Card"]
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


def fetch_template(item_type: str):
    try:
        template = subprocess.run([
            "op", "item", "template", "get", item_type,
            "--format=json"
        ], check=True, capture_output=True)
        return json.loads(template.stdout)
    except:
        logging.warning(f"An error occurred when attempting to fetch the {item_type} item template.")

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


class TemplateGenerator:
    __AVAILABLE_TEMPLATE_TYPES = ["Login", "Secure Note", "Credit Card", "Bank Account"]

    def __init__(self, lpass_raw_data: LPassData):
        self.template_type = None
        self.parsed_notes_data = {}
        self.lpass_raw_data = lpass_raw_data

        if lpass_raw_data.url == "http://sn":
            self._parse_notes()
            if not self.lpass_raw_data.notes.startswith("NoteType:"):
                self.template_type = "Secure Note"
            else:
                self.template_type = self.parsed_notes_data["NoteType"]
        else:
            self.template_type = "Login"

    def generate(self):
        if self.template_type not in self.__AVAILABLE_TEMPLATE_TYPES:
            return

        if self.template_type == "Login":
            template = self._login_template()
        elif self.template_type == "Secure Note":
            template = self._secure_note_template()
        elif self.template_type == "Credit Card":
            template = self._credit_card_template()
        elif self.template_type == "Bank Account":
            template = self._bank_account_template()
        else:
            return

        template["tags"] = ["LastPass"]
        return template

    def _parse_notes(self):
        try:
            entries = self.lpass_raw_data.notes.split("\n")
            for row in entries:
                [key, value] = row.split(":")
                self.parsed_notes_data[key] = value
            return self.parsed_notes_data
        except:
            pass  # silence error here but prints in the vault_item_import.py

    def _secure_note_template(self):
        template = dict()
        template["category"] = "SECURE_NOTE"
        template["title"] = self.lpass_raw_data.title
        template["fields"] = [
            {
                "id": "notesPlain",
                "type": "STRING",
                "purpose": "NOTES",
                "label": "notesPlain",
                "value": self.lpass_raw_data.notes
            }
        ]
        return template

    def _credit_card_template(self):
        template = dict()
        template["category"] = "CREDIT_CARD"
        template["title"] = self.lpass_raw_data.title
        template["fields"] = [
            {
                "id": "notesPlain",
                "type": "STRING",
                "purpose": "NOTES",
                "label": "notesPlain",
                "value": self.parsed_notes_data["Notes"]
            },
            {
                "id": "cardholder",
                "type": "STRING",
                "label": "cardholder name",
                "value": self.parsed_notes_data["Name on Card"]
            },
            {
                "id": "type",
                "type": "CREDIT_CARD_TYPE",
                "label": "type",
                "value": self.parsed_notes_data["Type"]
            },
            {
                "id": "ccnum",
                "type": "CREDIT_CARD_NUMBER",
                "label": "number",
                "value": self.parsed_notes_data["Number"]
            },
            {
                "id": "cvv",
                "type": "CONCEALED",
                "label": "verification number",
                "value": self.parsed_notes_data["Security Code"]
            },
            {
                "id": "expiry",
                "type": "MONTH_YEAR",
                "label": "expiry date",
                "value": utils.lpass_date_to_1password_format(self.parsed_notes_data["Expiration Date"])
            },
            {
                "id": "validFrom",
                "type": "MONTH_YEAR",
                "label": "valid from",
                "value": utils.lpass_date_to_1password_format(self.parsed_notes_data["Start Date"])
            },
        ]
        return template

    def _bank_account_template(self):
        template = dict()
        template["category"] = "BANK_ACCOUNT"
        template["title"] = self.lpass_raw_data.title
        template["fields"] = [
            {
                "id": "notesPlain",
                "type": "STRING",
                "purpose": "NOTES",
                "label": "notesPlain",
                "value": self.parsed_notes_data["Notes"]
            },
            {
                "id": "bankName",
                "type": "STRING",
                "label": "bank name",
                "value": self.parsed_notes_data["Bank Name"]
            },
            {
                "id": "accountType",
                "type": "MENU",
                "label": "type",
                "value": self.parsed_notes_data["Account Type"]
            },
            {
                "id": "routingNo",
                "type": "STRING",
                "label": "routing number",
                "value": self.parsed_notes_data["Routing Number"]
            },
            {
                "id": "accountNo",
                "type": "STRING",
                "label": "account number",
                "value": self.parsed_notes_data["Account Number"]
            },
            {
                "id": "swift",
                "type": "STRING",
                "label": "SWIFT",
                "value": self.parsed_notes_data["SWIFT Code"]
            },
            {
                "id": "iban",
                "type": "STRING",
                "label": "IBAN",
                "value": self.parsed_notes_data["IBAN Number"]
            },
            {
                "id": "telephonePin",
                "type": "CONCEALED",
                "label": "PIN",
                "value": self.parsed_notes_data["Pin"]
            },
            {
                "id": "branchPhone",
                "section": {
                    "id": "branchInfo",
                    "label": "Branch Information"
                },
                "type": "PHONE",
                "label": "phone",
                "value": self.parsed_notes_data["Branch Phone"]
            },
            {
                "id": "branchAddress",
                "section": {
                    "id": "branchInfo",
                    "label": "Branch Information"
                },
                "type": "STRING",
                "label": "address",
                "value": self.parsed_notes_data["Branch Address"]
            }
        ]
        return template

    def _login_template(self):
        template = dict()
        template["category"] = "LOGIN"
        template["title"] = self.lpass_raw_data.title or "Untitled Login"
        template["urls"] = [
            {
                "label": "website",
                "primary": True,
                "href": self.lpass_raw_data.url or "no URL"
            }
        ]
        template["fields"] = [
             {
                 "id": "username",
                 "type": "STRING",
                 "purpose": "USERNAME",
                 "label": "username",
                 "value": self.lpass_raw_data.username
             },
             {
                 "id": "password",
                 "type": "CONCEALED",
                 "purpose": "PASSWORD",
                 "label": "password",
                 "password_details": {
                     "strength": "TERRIBLE"
                 },
                 "value": self.lpass_raw_data.password
             },
             {
                 "id": "notesPlain",
                 "type": "STRING",
                 "purpose": "NOTES",
                 "label": "notesPlain",
                 "value": self.lpass_raw_data.notes
             }
        ] + ([{
            "id": "one-time password",
            "type": "OTP",
            "label": "one-time password",
            "value": self.lpass_raw_data.otp_secret
        }] if self.lpass_raw_data.otp_secret else [])
        return template

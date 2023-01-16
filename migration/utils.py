import re


def normalize_vault_name(vault_name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9\s]', "_", vault_name)

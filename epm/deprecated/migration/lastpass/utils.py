import re
import calendar


def normalize_vault_name(vault_name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9\s-]', "_", vault_name)


def lpass_date_to_1password_format(lpass_date: str) -> str:
    if not lpass_date:
        return ""
    [month, year] = lpass_date.split(",")
    monthNumber = list(calendar.month_abbr).index(month[:3])
    if monthNumber < 10:
        return year + "0" + str(monthNumber)

    return year + str(monthNumber)

# A debug script people simply migrating from LastPass to 1Password
# can disregard as it is not used in the process migrating. 
import utils


def test_normalize_vault_name():
    assert utils.normalize_vault_name("dev\sub_dev\\nested folder") == "dev_sub_dev_nested folder"
    assert utils.normalize_vault_name("dev/sub_dev") == "dev_sub_dev"


def test_lpass_date_to_1password():
    date = utils.lpass_date_to_1password_format("October,2025")
    assert date == "202510"

    date2 = utils.lpass_date_to_1password_format("December,2023")
    assert date2 == "202312"

    date3 = utils.lpass_date_to_1password_format("January,2020")
    assert date3 == "202001"

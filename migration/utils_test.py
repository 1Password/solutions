# A debug script people simply migrating from LastPass to 1Password
# can disregard as it is not used in the process migrating. 
from utils import normalize_vault_name


def test_normalize_vault_name():
    assert normalize_vault_name("dev\sub_dev\\nested folder") == "dev_sub_dev_nested folder"
    assert normalize_vault_name("dev/sub_dev") == "dev_sub_dev"

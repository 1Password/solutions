from template_generator import LPassData, TemplateGenerator


def test_template_generator_credit_card():
    lpass_data = LPassData(
        url="http://sn",
        username="",
        password="",
        otp_secret="",
        notes="NoteType:Credit Card\nLanguage:en-GB\nName on Card:Test User\nType:card type\nNumber:4141414141414141\nSecurity Code:123\nStart Date:December,2020\nExpiration Date:October,2025\nNotes:Fake credit card",
        title="Fake card",
        vault="test",
    )
    template = TemplateGenerator(lpass_data).generate()
    assert template['title'] == 'Fake card'
    assert template['category'] == 'CREDIT_CARD'

    for field in template['fields']:
        if field['id'] == 'validFrom':
            assert field['value'] == '202012'
        elif field['id'] == 'expiry':
            assert field['value'] == '202510'
        elif field['id'] == 'cvv':
            assert field['value'] == '123'
        elif field['id'] == 'ccnum':
            assert field['value'] == '4141414141414141'
        elif field['id'] == 'type':
            assert field['value'] == 'card type'
        elif field['id'] == 'cardholder':
            assert field['value'] == 'Test User'
        elif field['id'] == 'notesPlain':
            assert field['value'] == 'Fake credit card'


def test_template_generator_bank_account():
    lpass_data = LPassData(
        url="http://sn",
        username="",
        password="",
        otp_secret="",
        notes="NoteType:Bank Account\nLanguage:en-GB\nBank Name:bank name\nAccount Type:account type\nRouting Number:routing number\nAccount Number:account number\nSWIFT Code:swift code\nIBAN Number:iban number\nPin:pin\nBranch Address:branch address\nBranch Phone:branch phone\nNotes:note",
        title="Fake bank account",
        vault="test",
    )
    template = TemplateGenerator(lpass_data).generate()
    assert template['title'] == 'Fake bank account'
    assert template['category'] == 'BANK_ACCOUNT'

    for field in template['fields']:
        if field['id'] == 'notesPlain':
            assert field['value'] == 'note'
        elif field['id'] == 'bankName':
            assert field['value'] == 'bank name'
        elif field['id'] == 'accountType':
            assert field['value'] == 'account type'
        elif field['id'] == 'routingNo':
            assert field['value'] == 'routing number'
        elif field['id'] == 'accountNo':
            assert field['value'] == 'account number'
        elif field['id'] == 'swift':
            assert field['value'] == 'swift code'
        elif field['id'] == 'iban':
            assert field['value'] == 'iban number'
        elif field['id'] == 'telephonePin':
            assert field['value'] == 'pin'
        elif field['id'] == 'branchPhone':
            assert field['value'] == 'branch phone'
        elif field['id'] == 'branchAddress':
            assert field['value'] == 'branch address'


def test_template_generator_secure_note():
    lpass_data = LPassData(
        url="http://sn",
        username="",
        password="",
        otp_secret="",
        notes="Some very important text",
        title="Secret message",
        vault="test",
    )
    template = TemplateGenerator(lpass_data).generate()
    assert template['title'] == 'Secret message'
    assert template['category'] == 'SECURE_NOTE'
    assert template['fields'][0]['value'] == 'Some very important text'

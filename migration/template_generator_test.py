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

import pytest

from duru.cleanup import clean_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Eee, bugün ııı deployment yapacağız.", "bugün deployment yapacağız."),
        ("Hmm... um, we need uh a rollback, erm, today.", "we need a rollback, today."),
        ("Merhaba, eee, dünya.", "Merhaba, dünya."),
        ("Eee. Hmmm. ııı...", ""),
        ("Hımm, bugün hımmm deployment yapalım.", "bugün deployment yapalım."),
        ("hım Hım hımmet hmmfoo hummus", "hım Hım hımmet hmmfoo hummus"),
        ("Yani bu şey, well, I like hummus.", "Yani bu şey, well, I like hummus."),
        ("eeek hmmmfoo uhuru umami durum hummus", "eeek hmmmfoo uhuru umami durum hummus"),
        ("Önce eee\nsonra hmm biter.", "Önce \nsonra biter."),
    ],
)
def test_remove_only_standalone_fillers(raw, expected):
    assert clean_text(raw) == expected


def test_protect_links_email_dotted_identifiers_and_code():
    literals = [
        "https://example.com/um?q=hmm",
        "um@example.com",
        "www.hmm.com",
        "obj.um",
        "`um = 'hmm'`",
        "```python\num = 'eee'\n```",
    ]
    for literal in literals:
        assert clean_text("eee " + literal + " hmm") == literal


def test_disabled_cleanup_does_not_remove_fillers():
    assert clean_text("eee um  hmm", enabled=False) == "eee um  hmm"


def test_aliases_are_exact_tokens_case_insensitive_and_do_not_cascade():
    assert clean_text(
        "next js next jsler deploy deployer DEPLOY",
        replacements={"next js": "Next.js", "deploy": "deployment", "deployment": "release"},
    ) == "Next.js next jsler deployment deployer deployment"


def test_aliases_preserve_structured_content():
    raw = "deploy `deploy` deploy@example.com https://site.test/deploy obj.deploy"
    assert clean_text(raw, replacements={"deploy": "deployment"}) == (
        "deployment `deploy` deploy@example.com https://site.test/deploy obj.deploy"
    )


def test_aliases_still_apply_when_filler_removal_disabled():
    assert clean_text("um next js", enabled=False, replacements={"next js": "Next.js"}) == "um Next.js"


def test_no_fuzzy_rewrite_or_whitespace_reformatting():
    raw = "This  is\n  intentional formatting, and yazılım."
    assert clean_text(raw, replacements={"yazilim": "software"}) == raw


def test_invalid_arguments_are_rejected():
    with pytest.raises(TypeError):
        clean_text(None)
    with pytest.raises(TypeError):
        clean_text("a", replacements=[])

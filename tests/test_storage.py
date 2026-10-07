import json
import os
import pytest
from duru.storage import load_settings, save_settings, validate_settings


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_preferences_are_encrypted_and_roundtrip(tmp_path):
    path = tmp_path / "preferences.dpapi"
    settings = {"terms": ["private-secret-unique"], "language": "en", "auto_insert": True}
    save_settings(settings, path)
    assert b"private-secret-unique" not in path.read_bytes()
    assert load_settings(path)["terms"] == settings["terms"]
    assert load_settings(path)["auto_insert"] is True
    assert not path.with_suffix(".tmp").exists()


def test_invalid_settings_cannot_enable_insertion():
    value = validate_settings({"auto_insert": "true", "language": "xx", "model": "../../bad",
                               "terms": [None, "GitHub", "GitHub"], "replacements": {"": "x"}})
    assert value["auto_insert"] is False
    assert value["model"] == "turbo-ov"
    assert value["language"] == "tr"
    assert value["terms"] == ["GitHub"]
    assert not value["replacements"]


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_tampered_preferences_fail_closed(tmp_path):
    path = tmp_path / "preferences.dpapi"
    path.write_bytes(b'not a protected DPAPI blob')
    with pytest.raises(OSError):
        load_settings(path)


def test_new_settings_enable_the_requested_one_key_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert validate_settings({})["auto_insert"] is True
    assert load_settings()["auto_insert"] is True


@pytest.mark.parametrize("invalid", [None, "true", 1, 0, [], {}])
def test_explicit_invalid_insertion_settings_fail_closed(invalid):
    assert validate_settings({"auto_insert": invalid})["auto_insert"] is False


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_legacy_settings_migrate_once_without_losing_dictionary(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = tmp_path / "Duru" / "preferences.dpapi"
    legacy.parent.mkdir()
    settings = {
        "model": "medium", "language": "en", "cleanup": False,
        "auto_insert": False, "terms": ["private-migration-term", "PostgreSQL"],
        "replacements": {"post gres": "PostgreSQL"},
    }
    save_settings(settings, legacy)
    original = legacy.read_bytes()

    migrated = load_settings()

    assert migrated == {**settings, "auto_insert": True}
    destination = tmp_path / "T-Voice" / "preferences.dpapi"
    assert destination.exists()
    assert b"private-migration-term" not in destination.read_bytes()
    assert b"PostgreSQL" not in destination.read_bytes()
    assert load_settings(destination) == migrated
    assert legacy.read_bytes() == original
    assert not destination.with_suffix(".tmp").exists()

    # A later explicit choice must survive repeated launches and the old file.
    migrated["auto_insert"] = False
    save_settings(migrated)
    assert load_settings() == migrated


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_existing_t_voice_settings_take_precedence_over_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = tmp_path / "Duru" / "preferences.dpapi"
    legacy.parent.mkdir()
    save_settings({"terms": ["old-term"], "auto_insert": True}, legacy)
    expected = validate_settings({"terms": ["current-term"], "auto_insert": False})
    save_settings(expected)
    assert load_settings() == expected


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_explicit_missing_settings_path_does_not_migrate_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = tmp_path / "Duru" / "preferences.dpapi"
    legacy.parent.mkdir()
    save_settings({"terms": ["old-term"]}, legacy)
    assert load_settings(tmp_path / "separate-settings.dpapi")["terms"] == []

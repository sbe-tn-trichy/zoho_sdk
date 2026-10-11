import pytest

from workflows.core import config


def test_alias_mapping_survives_flattening():
    aliases = {"TEST-GSTIN": "Firm"}
    flattened = config._flatten_profile({"core": {"gstin_aliases": aliases}})
    assert flattened["gstin_aliases"] == aliases
    assert "gstin_aliases_test-gstin" not in flattened
    flat = config._flatten_profile({"gstin_aliases": aliases})
    assert flat["gstin_aliases"] == aliases
    assert "test-gstin" not in flat


def test_financial_credit_mapping_survives_flattening():
    notes = {"CN1": "Financial credit note"}
    flattened = config._flatten_profile({"gstr1_financial_credit_notes": notes})
    assert flattened["gstr1_financial_credit_notes"] == notes
    assert "cn1" not in flattened


def test_environment_aliases_override_file(monkeypatch):
    monkeypatch.setattr(config, "_FILE_CONFIG", {"gstin_aliases": {"FILE": "File"}})
    monkeypatch.delenv("GSTIN_ALIASES", raising=False)
    assert config.get_mapping_config("GSTIN_ALIASES") == {"FILE": "File"}
    monkeypatch.setenv("GSTIN_ALIASES", '{"ENV": "Environment"}')
    assert config.get_mapping_config("GSTIN_ALIASES") == {"ENV": "Environment"}


@pytest.mark.parametrize("value", ['["Firm"]', 'invalid'])
def test_invalid_alias_mapping_fails(monkeypatch, value):
    monkeypatch.setenv("GSTIN_ALIASES", value)
    with pytest.raises(ValueError, match="GSTIN_ALIASES"):
        config.get_mapping_config("GSTIN_ALIASES")

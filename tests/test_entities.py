from arvectum_data.entities import normalize_entity_value


def test_entity_value_normalization_is_conservative_and_deterministic() -> None:
    assert normalize_entity_value("  ООО   Ромашка  ") == "ооо ромашка"
    assert normalize_entity_value("ＡＢＣ  Corp") == "abc corp"
    assert normalize_entity_value("Straße") == "strasse"

from src.collection.outlet_catalog import (
    OUTLET_DEFINITIONS,
    get_outlet_registry_metadata,
    resolve_outlet_class,
)


def test_registry_metadata_is_generated_for_every_configured_outlet():
    metadata = get_outlet_registry_metadata()

    assert len(metadata) == len(OUTLET_DEFINITIONS) == 13
    assert {entry["name"] for entry in metadata} == {
        definition.name for definition in OUTLET_DEFINITIONS
    }
    assert all(entry["domain"] for entry in metadata)
    assert all(entry["scraper_class"] for entry in metadata)


def test_every_configured_url_resolves_to_its_scraper_class():
    for definition in OUTLET_DEFINITIONS:
        assert resolve_outlet_class(definition.url) is definition.scraper_class

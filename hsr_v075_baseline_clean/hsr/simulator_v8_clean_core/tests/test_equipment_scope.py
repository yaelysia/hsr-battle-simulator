"""Selected source catalogs preserve the full catalog's numerical definitions."""
from pathlib import Path
import copy
import json

import pytest

from hsr.simulator_v8_clean_core.tbgd.equipment_scope import build_equipment_scope
from hsr.simulator_v8_clean_core.tbgd.light_cone_cards import build_light_cone_catalog
from hsr.simulator_v8_clean_core.tbgd.relic_cards import build_relic_catalog

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[4] / 'turnbasedgamedata-main'


def without_source(value):
    if isinstance(value, dict):
        return {key: without_source(item) for key, item in value.items() if key != 'source'}
    if isinstance(value, (list, tuple)):
        return [without_source(item) for item in value]
    return value


@pytest.fixture(scope='module')
def full_catalogs():
    return build_light_cone_catalog(ROOT), build_relic_catalog(ROOT)


@pytest.mark.parametrize('cone_ids,template_ids', [
    (frozenset({'23002'}), frozenset()),
    (frozenset(), frozenset({'61021'})),
    (frozenset(), frozenset({'63025'})),
    (frozenset({'23002', '23013'}), frozenset({'61021', '63025'})),
])
def test_selected_catalog_matches_full_definitions(full_catalogs, cone_ids, template_ids):
    selected = build_equipment_scope(ROOT, cone_ids, template_ids)
    for partial, full in zip(selected, full_catalogs):
        if partial is None:
            continue
        assert partial.catalog_complete, partial.issues
        if hasattr(partial, 'canonical_definitions'):
            definitions, originals = partial.canonical_definitions, full.canonical_definitions
            assert {d.definition_key.definition_identity for d in definitions} == cone_ids
        else:
            definitions, originals = partial.canonical_catalog.definitions(), full.canonical_catalog.definitions()
            assert len(partial.canonical_catalog.set_definitions) <= len(template_ids)
        by_key = {d.definition_key: d for d in originals}
        selected_keys = {d.definition_key.stable_id for d in definitions}
        for definition in definitions:
            actual = without_source(definition.to_json())
            expected = without_source(by_key[definition.definition_key].to_json())
            # Domain membership narrows with the catalog; numerical definitions
            # and the selected sets' complete membership remain unchanged.
            if 'set_keys' in expected:
                expected['set_keys'] = [key for key in expected['set_keys'] if key['stable_id'] in selected_keys]
            assert actual == expected


def test_missing_selected_equipment_is_rejected():
    with pytest.raises(ValueError, match='light cone source missing'):
        build_equipment_scope(ROOT, frozenset({'does-not-exist'}), frozenset())
    with pytest.raises(ValueError, match='relic template source missing'):
        build_equipment_scope(ROOT, frozenset(), frozenset({'does-not-exist'}))


def test_compile_pool_unions_equipment_without_expanding_to_full_catalog(monkeypatch):
    from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
    from hsr.simulator_v8_clean_core.tbgd.battle_catalog import build_battle_rulebook
    from hsr.simulator_v8_clean_core.tbgd.lowering import TBGDLowering
    data = json.loads((Path(__file__).resolve().parents[1] / 'examples/cli/arlan_lv80_full_traces_two_waves.json').read_text())
    pool = {'light_cone_ids': ['23002', '23013'], 'relic_template_ids': ['61021', '61022', '61023', '61024', '63025', '63026']}
    data['battle_setup']['metadata']['compile_scope'] = pool
    scopes = []
    def build(self, **scope):
        scopes.append(scope)
        return CanonicalIR(version='scope_fixture')
    monkeypatch.setattr(TBGDLowering, 'build', build)
    build_battle_rulebook(ROOT, data)
    changed = copy.deepcopy(data)
    changed['units'][0]['character_build']['equipment_build']['light_cone'] = None
    changed['units'][0]['character_build']['equipment_build'].pop('build_fingerprint', None)
    changed['units'][0]['character_build'].pop('input_fingerprint', None)
    build_battle_rulebook(ROOT, changed)
    assert scopes[0] == scopes[1]
    assert scopes[0]['light_cone_ids'] == frozenset(pool['light_cone_ids'])
    build_battle_rulebook(ROOT, data, include_equipment=True)
    assert scopes[-1]['light_cone_ids'] is None and scopes[-1]['relic_template_ids'] is None

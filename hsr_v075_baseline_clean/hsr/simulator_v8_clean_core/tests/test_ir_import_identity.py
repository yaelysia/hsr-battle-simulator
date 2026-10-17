"""UI/CLI import spelling cannot change the identity of the same rule data."""
import importlib
from pathlib import Path

from hsr.simulator_v8_clean_core.builds.manifest import canonical_ir_fingerprint
from hsr.simulator_v8_clean_core.rules import ir as qualified


def test_rule_fingerprint_is_independent_of_internal_import_prefix(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    bare = importlib.import_module('simulator_v8_clean_core.rules.ir')
    def content(module, amount):
        return module.CanonicalIR('test', effects=(module.EffectIR(
            'effect', 'fixture', {'value': amount}, module.IRSource('synthetic', 'validation', 'source'),
        ),))
    expected = canonical_ir_fingerprint(content(qualified, 1))
    assert canonical_ir_fingerprint(content(bare, 1)) == expected
    assert canonical_ir_fingerprint(content(bare, 2)) != expected
    assert canonical_ir_fingerprint(content(bare, 1.0)) != expected

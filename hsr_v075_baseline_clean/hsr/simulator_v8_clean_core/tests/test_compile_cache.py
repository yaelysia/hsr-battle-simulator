"""Persistent IR reuse, invalidation, immutable sharing, and safe publication."""
import io
import os
import pickle
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import MappingProxyType

import pytest

from hsr.simulator_v8_clean_core import BASELINE_VERSION
from hsr.simulator_v8_clean_core.immutable_json import FrozenJSONDict, FrozenJSONList, freeze_json
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, ConditionIR, IRSource
from hsr.simulator_v8_clean_core.tbgd.compile_cache import (
    _IRPickler, _IRUnpickler, _cache_key, _read_cache, _source_entries, cached_ir,
)
from hsr.simulator_v8_clean_core.tbgd.lowering import LoweringLimits


def _source(tmp_path):
    root = tmp_path / 'source'
    (root / 'Config').mkdir(parents=True)
    (root / 'ExcelOutput').mkdir()
    (root / 'Config/ability.json').write_text('{"value":1}')
    return root


def _ir():
    context = freeze_json({'parameters': [1, 2]})
    condition = ConditionIR('fixture', 'unknown', {'nested': [{'value': 1}]},
                            IRSource('fixture.json', 'unknown', 'fixture'))
    return CanonicalIR(version=BASELINE_VERSION, conditions=(condition,),
                       metadata={'first': context, 'second': context})


def test_cold_then_warm_preserves_typed_ir_and_shared_immutable_subtrees(tmp_path):
    root, cache = _source(tmp_path), tmp_path / 'cache'
    calls = []
    def build():
        calls.append(1)
        return _ir()
    cold = cached_ir(root, LoweringLimits(), {}, build, cache_dir=cache)
    warm = cached_ir(root, LoweringLimits(), {}, build, cache_dir=cache)
    assert len(calls) == 1 and warm == cold and warm is not cold
    assert type(warm) is CanonicalIR
    context = warm.metadata['first']
    assert context is warm.metadata['second'] and type(context) is FrozenJSONDict
    assert type(context['parameters']) is FrozenJSONList
    with pytest.raises(TypeError):
        context['parameters'].append(3)
    with pytest.raises(TypeError):
        warm.conditions[0].payload['nested'].append({})
    with pytest.raises(TypeError):
        warm.conditions[0].payload['nested'][0]['value'] = 2
    assert warm.to_json() == cold.to_json()
    assert not list(cache.glob('*.tmp'))
    # A separate process and the UI import spelling must reuse the same artifact.
    key = _cache_key(root, LoweringLimits(), {})
    path, = cache.glob('*.ir.gz')
    script = ('from pathlib import Path; from simulator_v8_clean_core.tbgd.compile_cache import _read_cache; '
              'from simulator_v8_clean_core.rules.ir import CanonicalIR; '
              f'ir = _read_cache(Path({str(path)!r}), {key!r}); '
              'assert type(ir) is CanonicalIR; assert ir.metadata["first"] is ir.metadata["second"]')
    subprocess.run([os.sys.executable, '-B', '-c', script], check=True,
        env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2])})


def test_warm_load_checks_source_generation_once(tmp_path, monkeypatch):
    from hsr.simulator_v8_clean_core.tbgd import compile_cache
    root, cache = _source(tmp_path), tmp_path / 'cache'
    cached_ir(root, LoweringLimits(), {}, _ir, cache_dir=cache)
    calls = []
    original = compile_cache._cache_key
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(compile_cache, '_cache_key', counted)
    cached_ir(root, LoweringLimits(), {}, _ir, cache_dir=cache)
    assert len(calls) == 1


def test_source_edit_even_with_restored_mtime_and_scope_limits_invalidate(tmp_path):
    root, cache = _source(tmp_path), tmp_path / 'cache'
    calls = []
    def build():
        calls.append(1)
        return _ir()
    first_key = _cache_key(root, LoweringLimits(), {})
    cached_ir(root, LoweringLimits(), {}, build, cache_dir=cache)
    path = root / 'Config/ability.json'
    stat = path.stat()
    path.write_text('{"value":2}')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert _cache_key(root, LoweringLimits(), {}) != first_key
    cached_ir(root, LoweringLimits(), {}, build, cache_dir=cache)
    cached_ir(root, LoweringLimits(), {'avatar_ids': ['1008']}, build, cache_dir=cache)
    cached_ir(root, LoweringLimits(max_ability_files=1), {}, build, cache_dir=cache)
    assert len(calls) == 4 and len(list(cache.glob('*.ir.gz'))) == 3
    before = _cache_key(root, LoweringLimits(), {})
    (root / 'Config/added.json').write_text('{}')
    assert _cache_key(root, LoweringLimits(), {}) != before
    (root / 'Config/added.json').unlink()
    assert _cache_key(root, LoweringLimits(), {}) == before
    (root / 'TextMap').mkdir()
    (root / 'TextMap/TextMapCHS.json').write_text('{"name":"display"}')
    assert _cache_key(root, LoweringLimits(), {}) != before


def test_compile_dependencies_invalidate_but_runtime_system_changes_do_not(tmp_path):
    root = _source(tmp_path)
    code = tmp_path / 'code'
    code.mkdir()
    source = code / 'lowering.py'
    source.write_text('VERSION = 1\n')
    (code / 'systems').mkdir()
    scheduler = code / 'systems/scheduler.py'
    scheduler.write_text('VERSION = 1\n')
    unit_stats = code / 'systems/unit_stats.py'
    unit_stats.write_text('VERSION = 1\n')
    (code / 'core').mkdir()
    executor = code / 'core/executor.py'
    executor.write_text('VERSION = 1\n')
    model = code / 'core/model.py'
    model.write_text('VERSION = 1\n')
    session = code / 'session.py'
    session.write_text('VERSION = 1\n')
    before = _cache_key(root, LoweringLimits(), {}, code_root=code)
    scheduler.write_text('VERSION = 2\n')
    executor.write_text('VERSION = 2\n')
    # The L3 session boundary has no L0 caller, so its edits keep the IR valid.
    session.write_text('VERSION = 2\n')
    assert _cache_key(root, LoweringLimits(), {}, code_root=code) == before
    unit_stats.write_text('VERSION = 2\n')
    after_stats = _cache_key(root, LoweringLimits(), {}, code_root=code)
    assert after_stats != before
    source.write_text('VERSION = 2\n')
    assert _cache_key(root, LoweringLimits(), {}, code_root=code) != after_stats
    before_model = _cache_key(root, LoweringLimits(), {}, code_root=code)
    model.write_text('VERSION = 2\n')
    assert _cache_key(root, LoweringLimits(), {}, code_root=code) != before_model


@pytest.mark.skipif(os.geteuid() == 0, reason='needs ordinary POSIX permission checks')
def test_denied_kind_check_keeps_rglob_visibility(tmp_path):
    # A nonmatching symlink whose target sits behind an unsearchable directory
    # makes the directory classification raise. Path.rglob still returns the
    # same-directory matches, so the scan must neither fail nor lose them.
    protected = tmp_path / 'protected'
    protected.mkdir()
    (protected / 'target').mkdir()
    code = tmp_path / 'code'
    code.mkdir()
    (code / 'lowering.py').write_text('VERSION = 1\n')
    for order in ('link_first', 'link_last'):
        root = tmp_path / order
        root.mkdir()
        if order == 'link_first':
            (root / 'opaque-link').symlink_to(protected / 'target')
        (root / 'ability.json').write_text('{}')
        (root / 'nested').mkdir()
        (root / 'nested' / 'inner.json').write_text('{}')
        if order == 'link_last':
            (root / 'opaque-link').symlink_to(protected / 'target')
        protected.chmod(0)
        try:
            native = [(str(path.relative_to(root)), (stat := path.stat()).st_size,
                       stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
                      for path in sorted(root.rglob('*.json'))]
            scanned = [(os.sep.join(parts), (stat := entry.stat()).st_size,
                        stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
                       for parts, entry in _source_entries(root, '.json')]
            assert scanned == native
            assert 'ability.json' in [name for name, *_ in scanned]
            key = _cache_key(root, LoweringLimits(), {}, code_root=code)
            assert len(key) == 64
        finally:
            protected.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason='needs ordinary POSIX permission checks')
def test_denied_stat_of_matching_entry_still_fails(tmp_path):
    # A matching name whose own metadata is unreadable stays visible to the scan
    # but must still fail the cache key, exactly like Path.rglob plus stat.
    protected = tmp_path / 'protected'
    protected.mkdir()
    (protected / 'target').mkdir()
    code = tmp_path / 'code'
    code.mkdir()
    (code / 'lowering.py').write_text('VERSION = 1\n')
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'ability.json').write_text('{}')
    (root / 'opaque.json').symlink_to(protected / 'target')
    protected.chmod(0)
    try:
        assert [os.sep.join(parts) for parts, _ in _source_entries(root, '.json')] == [
            'ability.json', 'opaque.json',
        ]
        with pytest.raises(PermissionError):
            [path.stat() for path in sorted(root.rglob('*.json'))]
        with pytest.raises(PermissionError):
            _cache_key(root, LoweringLimits(), {}, code_root=code)
    finally:
        protected.chmod(0o700)


def test_corrupt_cache_rebuilds_and_failed_build_publishes_nothing(tmp_path):
    root, cache = _source(tmp_path), tmp_path / 'cache'
    calls = []
    def build():
        calls.append(1)
        return _ir()
    cached_ir(root, LoweringLimits(), {}, build, cache_dir=cache)
    path, = cache.glob('*.ir.gz')
    path.write_bytes(path.read_bytes()[:-3])
    assert _read_cache(path, _cache_key(root, LoweringLimits(), {})) is None
    cached_ir(root, LoweringLimits(), {}, build, cache_dir=cache)
    assert len(calls) == 2
    def fail():
        raise ValueError('source semantics unknown')
    with pytest.raises(ValueError, match='semantics unknown'):
        cached_ir(root, LoweringLimits(), {'different': True}, fail, cache_dir=cache)
    assert len(list(cache.glob('*.ir.gz'))) == 1 and not list(cache.glob('*.tmp'))


def test_source_changed_during_build_is_not_published(tmp_path):
    root, cache = _source(tmp_path), tmp_path / 'cache'
    def build():
        (root / 'Config/ability.json').write_text('{"value":3}')
        return _ir()
    with pytest.raises(RuntimeError, match='changed during IR compilation'):
        cached_ir(root, LoweringLimits(), {}, build, cache_dir=cache)
    assert not list(cache.glob('*.ir.gz'))


def test_concurrent_cold_requests_compile_once(tmp_path):
    root, cache = _source(tmp_path), tmp_path / 'cache'
    calls = []
    def build():
        calls.append(1)
        return _ir()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: cached_ir(root, LoweringLimits(), {}, build,
                                                     cache_dir=cache), range(2)))
    assert len(calls) == 1 and results[0] == results[1]
    assert len(list(cache.glob('*.ir.gz'))) == 1 and not list(cache.glob('*.tmp'))


@pytest.mark.parametrize('cache_available', [True, False])
def test_compiled_rule_identity_never_rehashes_ir(tmp_path, monkeypatch, cache_available):
    from hsr.simulator_v8_clean_core.builds import manifest
    from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
    from hsr.simulator_v8_clean_core.tbgd.compile_cache import ir_cache_slot
    root, cache = _source(tmp_path), tmp_path / 'cache'
    if not cache_available:
        cache.write_text('a file prevents cache directory creation')
    ir = cached_ir(root, LoweringLimits(), {}, _ir, cache_dir=cache)
    def no_rehash(*args):
        raise AssertionError('compiled identity must use validated build inputs')
    monkeypatch.setattr(manifest, 'canonical_ir_fingerprint', no_rehash)
    monkeypatch.setattr(manifest, '_source_fingerprint', no_rehash)
    rules = RuleBook(ir)
    identity = manifest.current_build_rule_identity(rules)
    assert identity.rules_fingerprint == ir_cache_slot(ir)[1]
    assert manifest.rulebook_fingerprint(rules) == identity.rules_fingerprint


def test_build_rule_identity_survives_a_new_process(tmp_path):
    from hsr.simulator_v8_clean_core.builds import manifest
    from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
    root, cache = _source(tmp_path), tmp_path / 'cache'
    condition = ConditionIR('fixture', 'unknown', {'nested': [{'value': 1}]},
                            IRSource('fixture.json', 'unknown', 'fixture'))
    fixture = CanonicalIR(version=BASELINE_VERSION, conditions=(condition,),
                          metadata={'light_cone_source_content_fingerprint': {'hash': 'fixture'}})
    ir = cached_ir(root, LoweringLimits(), {}, lambda: fixture, cache_dir=cache)
    expected = manifest.current_build_rule_identity(RuleBook(ir=ir)).rules_fingerprint
    script = (
        'from pathlib import Path\n'
        'from simulator_v8_clean_core.tbgd.compile_cache import cached_ir\n'
        'from simulator_v8_clean_core.tbgd.lowering import LoweringLimits\n'
        'from simulator_v8_clean_core.rules.rulebook import RuleBook\n'
        'from simulator_v8_clean_core.builds import manifest\n'
        'def cold():\n'
        '    raise AssertionError("warm cache must not rebuild")\n'
        f'ir = cached_ir(Path({str(root)!r}), LoweringLimits(), {{}}, cold, cache_dir=Path({str(cache)!r}))\n'
        'def no_rehash(ir):\n'
        '    raise AssertionError("warm identity must not rehash")\n'
        'manifest.canonical_ir_fingerprint = no_rehash\n'
        'print(manifest.current_build_rule_identity(RuleBook(ir=ir)).rules_fingerprint)\n'
    )
    result = subprocess.run([os.sys.executable, '-B', '-c', script], check=True,
        capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2])})
    assert result.stdout.strip() == expected


def test_mapping_proxy_roundtrip_and_executable_pickle_globals_are_rejected():
    from hsr.simulator_v8_clean_core.equipment.models import EquipmentDefinitionKey
    key = EquipmentDefinitionKey('light_cone', 'fixture')
    buffer = io.BytesIO()
    _IRPickler(buffer, protocol=pickle.HIGHEST_PROTOCOL).dump((MappingProxyType({'value': 1}), key))
    restored, restored_key = _IRUnpickler(io.BytesIO(buffer.getvalue())).load()
    assert type(restored) is MappingProxyType and restored['value'] == 1
    assert type(restored_key) is EquipmentDefinitionKey and restored_key == key
    with pytest.raises(TypeError):
        restored['value'] = 2
    with pytest.raises(pickle.UnpicklingError, match='outside the IR package'):
        _IRUnpickler(io.BytesIO(pickle.dumps(os.system))).load()

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from hsr.simulator_v8_clean_core.battle_archive import (
    read_archive,
    verify_archive,
    write_archive,
)
from hsr.simulator_v8_clean_core.cli import main as cli_main
from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR
from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
from hsr.simulator_v8_clean_core.session import SESSION_SCHEMA


class BattleArchiveTest(unittest.TestCase):
    def test_session_accept_reads_outcome_without_exporting_the_transition(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from hsr.simulator_v8_clean_core.session import BattleSession

        before, after = object(), object()
        session = BattleSession.__new__(BattleSession)
        for category, eligible in (("committed", True), ("committed", False), ("blocked", True)):
            transition = SimpleNamespace(
                outcome=SimpleNamespace(to_json=lambda: {"category": category, "successor_eligible": eligible}),
                to_json=Mock(side_effect=AssertionError("full audit export is unnecessary for state acceptance")),
            )
            session.state = before
            session._accept(SimpleNamespace(after_state=after, transition=transition))
            self.assertIs(session.state, after if category == "committed" and eligible else before)
            transition.to_json.assert_not_called()

    def test_read_rejects_duplicate_keys_and_non_finite_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate key"):
                read_archive(path)

            path.write_text('{"value":NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite"):
                read_archive(path)
            path.write_text('{"value":1e9999}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite"):
                read_archive(path)

    def test_write_is_atomic_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            write_archive(path, {"value": 1})
            self.assertEqual(read_archive(path), {"value": 1})
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                write_archive(path, {"value": 2})
            self.assertEqual(read_archive(path), {"value": 1})

    def test_verify_rejects_rule_fingerprint_before_session_rebuild(self):
        archive = {
            "schema_version": SESSION_SCHEMA,
            "canonical_ir_fingerprint": "not-the-current-rules",
            "scenario": {},
            "initial_snapshot": {},
            "initialization": {},
            "operations": [],
            "final_snapshot": {},
            "outcome": "",
        }
        result = verify_archive(archive, RuleBook(CanonicalIR(version="archive-test")))
        self.assertEqual(
            result,
            {
                "ok": False,
                "step_count": 0,
                "errors": ["canonical_ir_fingerprint_mismatch"],
            },
        )

    def test_cli_rejects_invalid_run_script_before_compile_or_archive_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = root / "scenario.json"
            script = root / "commands.json"
            output = root / "session.json"
            scenario.write_text("{}", encoding="utf-8")
            script.write_text('{"commands":[{}]}', encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = cli_main([
                    "--data-root", str(root / "missing-data-root"),
                    "run", str(scenario), "--commands", str(script), "--output", str(output),
                ])
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())
            self.assertIn("actor_id", stderr.getvalue())
def test_compressed_archive_round_trip_and_no_overwrite(tmp_path):
    from hsr.simulator_v8_clean_core.battle_archive import read_archive, write_archive
    target = tmp_path / "battle.json.gz"
    data = {"文本": "战斗记录", "repeated": ["source" * 500] * 50}
    write_archive(target, data)
    assert target.stat().st_size < 2000
    assert read_archive(target) == data
    try:
        write_archive(target, {"overwrite": True})
    except FileExistsError:
        pass
    else:
        raise AssertionError("compressed archive was overwritten")
    assert read_archive(target) == data


def test_graph_archive_preserves_canonical_json_and_cleans_invalid_partial_write(tmp_path):
    import gzip
    import json
    import pytest

    data = {"文本": "战斗记录", "a": list(range(100))}
    from hsr.simulator_v8_clean_core.archive_json import encode_archive_json
    expected = (json.dumps(encode_archive_json(data), allow_nan=False, ensure_ascii=False,
                           separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    for suffix in (".json", ".json.gz"):
        target = tmp_path / ("battle" + suffix)
        write_archive(target, data)
        actual = gzip.decompress(target.read_bytes()) if suffix.endswith(".gz") else target.read_bytes()
        assert actual == expected
        invalid = tmp_path / ("invalid" + suffix)
        with pytest.raises(ValueError, match="not strict JSON"):
            write_archive(invalid, {"a": "valid prefix", "z": float("nan")})
        assert not invalid.exists()
        assert not list(tmp_path.glob(".*.tmp"))


def test_archive_validation_rejects_invalid_json_in_later_operations():
    import pytest
    from hsr.simulator_v8_clean_core.battle_archive import _validate_archive_shape

    archive = dict(schema_version=SESSION_SCHEMA, canonical_ir_fingerprint="synthetic:fingerprint",
                   scenario={}, initial_snapshot={}, setup_audit={}, initialization={},
                   final_snapshot={}, outcome="", operations=[{"valid": 1}])
    _validate_archive_shape(archive)
    for invalid in (float("nan"), {"unsupported"}, []):
        if isinstance(invalid, list):
            invalid.append(invalid)
        archive["operations"] = [{"valid": 1}, {"invalid": invalid}]
        with pytest.raises((TypeError, ValueError)):
            _validate_archive_shape(archive)


def test_structural_replay_comparison_keeps_canonical_json_value_distinctions():
    from hsr.simulator_v8_clean_core.battle_archive import _json_equal

    assert _json_equal({"b": (1, {"文本": "来源"}), "a": 1.0}, {"a": 1.0, "b": [1, {"文本": "来源"}]})
    for left, right in ((1, 1.0), (True, 1), (-0.0, 0.0), ([1, 2], [2, 1]), ({"a": 1}, {"b": 1})):
        assert not _json_equal({"value": left}, {"value": right})
    assert _json_equal({1: "Python key"}, {"1": "Python key"})


def test_graph_archive_shares_nested_evidence_and_preserves_scalar_types(tmp_path):
    import json
    from hsr.simulator_v8_clean_core.archive_json import encode_archive_json
    from hsr.simulator_v8_clean_core.battle_archive import _json_equal, replay_archive

    evidence = {"source": '引用"\\\n😀结束', "values": [True, None, 1, 1.0, -0.0, 0.0], "$ref": 123}
    branch = evidence
    for _ in range(18):
        branch = [branch, branch]
    data = {"left": branch, "right": branch, "equal_copy": dict(evidence), "evidence": evidence}
    encoded = encode_archive_json(data)
    assert len(encoded["objects"]) == 21
    assert len(json.dumps(encoded)) < 3000
    for suffix in (".json", ".json.gz"):
        path = tmp_path / ("shared" + suffix)
        write_archive(path, data)
        decoded = read_archive(path)
        assert decoded["left"] is decoded["right"]
        assert decoded["evidence"] is decoded["equal_copy"]
        assert _json_equal(decoded, data)
        cursor = decoded["left"]
        for _ in range(18):
            assert cursor[0] is cursor[1]
            cursor = cursor[0]
        assert cursor is decoded["evidence"]

    archive = dict(schema_version=SESSION_SCHEMA, canonical_ir_fingerprint="not-current",
                   scenario={}, initial_snapshot={}, setup_audit={}, initialization={},
                   final_snapshot={}, outcome="", operations=[])
    rules = RuleBook(CanonicalIR(version="archive-test"))
    path = tmp_path / "replay.json.gz"
    write_archive(path, archive)
    assert replay_archive(path, lambda scenario: rules) == verify_archive(archive, rules)


def test_graph_archive_rejects_malformed_references_and_old_format(tmp_path):
    import gzip
    import json
    import pytest
    from hsr.simulator_v8_clean_core.archive_json import ARCHIVE_FORMAT, decode_archive_json

    invalid_objects = [
        [["object", {"self": {"$ref": 0}}]],
        [["object", {"bad": {"$ref": -1}}]],
        [["object", {"bad": {"$ref": True}}]],
        [["object", {}], ["object", {"bad": {"$ref": 0, "extra": 1}}]],
        [["object", {}], ["object", {}]],
        [["unknown", {}]], [["object", []]], [["array", {}]], [["array", []]],
        [["object", {"bad": []}]], [["object", {"bad": float("nan")}]],
    ]
    for records in invalid_objects:
        with pytest.raises(ValueError):
            decode_archive_json({"format": ARCHIVE_FORMAT, "root": len(records) - 1, "objects": records})
    for root in (True, -1, 1, None):
        with pytest.raises(ValueError):
            decode_archive_json({"format": ARCHIVE_FORMAT, "root": root, "objects": [["object", {}]]})
    path = tmp_path / "invalid.json"
    for malformed in ('{}', '{"operations":[]}',
                      '{"objects":[],"objects":[]}', '{"value":NaN}', '{"value":1e9999}',
                      '{"x":1,}', '{} trailing', '["unterminated]'):
        path.write_text(malformed, encoding="utf-8")
        with pytest.raises(ValueError):
            read_archive(path)
    for invalid in (float("nan"), {"unsupported"}, {1: "coerced"}):
        with pytest.raises(ValueError, match="not strict JSON"):
            write_archive(tmp_path / "invalid-write.json", {"invalid": invalid})
    circular = []
    circular.append(circular)
    with pytest.raises(ValueError, match="circular"):
        write_archive(tmp_path / "circular.json", {"invalid": circular})
    for suffix in (".json", ".json.gz"):
        path = tmp_path / ("invalid-utf8" + suffix)
        path.write_bytes(gzip.compress(b'{"bad":"\xff"}') if suffix.endswith(".gz") else b'{"bad":"\xff"}')
        with pytest.raises(ValueError, match="not valid UTF-8"):
            read_archive(path)

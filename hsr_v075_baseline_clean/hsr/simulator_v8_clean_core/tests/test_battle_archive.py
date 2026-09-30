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

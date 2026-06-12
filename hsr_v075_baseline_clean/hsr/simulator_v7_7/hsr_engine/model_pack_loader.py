from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import yaml

from .schema_normalizer import canonicalize_case, normalize_action, normalize_status_def, normalize_triggers
from .core_rules import normalize_flag_values, normalize_str_list, coerce_float


class ModelPackError(RuntimeError):
    pass


def read_yaml(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class ModelPack:
    """Loader for canonical hsr_model_pack v3.x directories.

    The simulator core should not parse scattered legacy model files directly.
    This loader consumes the normalized model pack manifest and returns canonical
    simulator cases.  For v3.0 the pack exposes precompiled simulator cases; the
    loader also validates and canonicalizes them before the battle engine sees them.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        if not self.root.exists():
            raise ModelPackError(f"Model pack path does not exist: {self.root}")
        manifest_path = self.root / "MANIFEST.yaml"
        if not manifest_path.exists():
            raise ModelPackError(f"Missing MANIFEST.yaml in model pack: {self.root}")
        self.manifest = read_yaml(manifest_path) or {}
        if self.manifest.get("kind") != "model_pack_manifest":
            raise ModelPackError(f"Not a model_pack_manifest: {manifest_path}")

    def resolve(self, rel: str | Path) -> Path:
        path = (self.root / rel).resolve()
        if not str(path).startswith(str(self.root)):
            raise ModelPackError(f"Ref escapes model pack root: {rel}")
        return path

    def load_ref(self, rel: str | Path) -> Any:
        return read_yaml(self.resolve(rel))

    def compiled_case_refs(self) -> dict[str, str]:
        refs: dict[str, str] = {}
        entry = self.manifest.get("entrypoints", {}) if isinstance(self.manifest.get("entrypoints"), dict) else {}
        default = entry.get("default_compiled_case")
        if default:
            refs["default"] = str(default)
            refs[Path(str(default)).stem] = str(default)
        compiled_dir = self.resolve(self.manifest.get("directories", {}).get("compiled_cases", "compiled_cases/"))
        if compiled_dir.exists():
            for p in sorted(compiled_dir.glob("*.yaml")):
                refs[p.stem] = str(p.relative_to(self.root))
        return refs

    def load_compiled_case(self, case_id: str | None = None) -> dict[str, Any]:
        refs = self.compiled_case_refs()
        key = case_id or "default"
        if key not in refs:
            available = ", ".join(sorted(refs))
            raise ModelPackError(f"Unknown compiled case '{key}'. Available: {available}")
        case = self.load_ref(refs[key]) or {}
        case.setdefault("model_pack", {"id": self.manifest.get("id"), "schema_version": self.manifest.get("schema_version")})
        return canonicalize_case(case)

    def load_battle_document(self, battle_id_or_ref: str | None = None) -> dict[str, Any]:
        entry = self.manifest.get("entrypoints", {}) if isinstance(self.manifest.get("entrypoints"), dict) else {}
        ref = battle_id_or_ref or entry.get("default_battle")
        if not ref:
            raise ModelPackError("No default battle in manifest")
        # Direct ref path is preferred; otherwise resolve by battles/<id>.yaml.
        p = self.resolve(ref)
        if not p.exists():
            p = self.resolve(f"battles/{battle_id_or_ref}.yaml")
        if not p.exists():
            raise ModelPackError(f"Battle document not found: {battle_id_or_ref or ref}")
        return self.load_ref(p.relative_to(self.root))

    def validate_index(self) -> dict[str, Any]:
        """Return a lightweight structural validation report for model-pack CI."""
        report: dict[str, Any] = {"manifest_id": self.manifest.get("id"), "ok": True, "checks": []}
        dirs = self.manifest.get("directories", {}) if isinstance(self.manifest.get("directories"), dict) else {}
        for name, rel in dirs.items():
            if name == "legacy_sources":
                continue
            exists = self.resolve(rel).exists()
            report["checks"].append({"type": "directory", "name": name, "path": rel, "ok": exists})
            report["ok"] = report["ok"] and exists
        refs = self.compiled_case_refs()
        if not refs:
            report["ok"] = False
            report["checks"].append({"type": "compiled_case", "ok": False, "message": "no compiled cases found"})
        else:
            for key, rel in sorted(refs.items()):
                if key == "default" and rel == refs.get(Path(rel).stem):
                    continue
                case = self.load_ref(rel)
                can = canonicalize_case(case)
                ok = isinstance(can.get("units"), dict) and bool(can.get("units"))
                report["ok"] = report["ok"] and ok
                report["checks"].append({"type": "compiled_case", "id": key, "path": rel, "ok": ok, "units": len(can.get("units", {})), "route_steps": len(can.get("route", []))})
        return report


def load_model_pack_case(model_pack_root: str | Path, case_id: str | None = None) -> dict[str, Any]:
    return ModelPack(model_pack_root).load_compiled_case(case_id)

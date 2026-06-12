from __future__ import annotations

"""Audit engine-side property usage in TurnBasedGameData ability graphs.

This module intentionally produces evidence reports only.  Properties such as
``AttackConvert`` are not normal combat-kernel stat names; the compiler/runtime
must not map them into formula buckets until source usage gives enough evidence.
"""

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import json
import zipfile

from .tbgd_loader import TBGDSource
from .engine_property_model import describe_engine_property


def _node_type(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("$type") or node.get("type") or "")
    return ""


def _unwrap_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value.keys()) == {"Value"}:
        return _unwrap_value(value.get("Value"))
    return value


def _property_name(node: dict[str, Any]) -> str | None:
    for key in ("Property", "Value"):
        if key in node:
            val = _unwrap_value(node.get(key))
            if isinstance(val, str):
                return val
    return None


def _dynamic_key(node: dict[str, Any]) -> str | None:
    val = node.get("DynamicKey")
    val = _unwrap_value(val)
    if isinstance(val, str):
        return val
    return None


def _modifier_name(node: dict[str, Any]) -> str | None:
    val = node.get("ModifierName")
    val = _unwrap_value(val)
    if isinstance(val, str):
        return val
    return None


def _target_alias(node: dict[str, Any], key: str = "TargetType") -> str | None:
    target = node.get(key)
    if isinstance(target, dict):
        if "Alias" in target:
            return str(target.get("Alias"))
        if "Value" in target:
            return str(target.get("Value"))
    return None


def _walk(obj: Any, path: str = ""):
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from _walk(v, f"{path}/{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


def _read_source_text(source: TBGDSource, rel: str) -> str | None:
    try:
        if source.zip_path:
            with zipfile.ZipFile(source.zip_path) as z:
                return z.read(source.prefix + rel).decode("utf-8", errors="ignore")
        p = source.root / rel
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    return None


def _iter_ability_files(source: TBGDSource) -> list[str]:
    files = [p for p in source.list_files("Config/ConfigAbility/") if p.endswith(".json") and not p.endswith(".layout.json")]
    return sorted(files)


def analyze_engine_property_usage(tbgd_source: str | Path | TBGDSource, property_name: str = "AttackConvert", *, sample_limit: int = 30) -> dict[str, Any]:
    """Scan ConfigAbility graphs for one engine-side property.

    The output is deliberately an audit/evidence artifact.  It records how a
    property is read/written/watched across source graphs and emits a conservative
    recommendation for compiler/runtime handling.
    """
    source = tbgd_source if isinstance(tbgd_source, TBGDSource) else TBGDSource.open(tbgd_source)
    usage_counter: Counter[str] = Counter()
    file_counter: Counter[str] = Counter()
    pair_counter: Counter[str] = Counter()
    dynamic_key_counter: Counter[str] = Counter()
    modifier_counter: Counter[str] = Counter()
    target_alias_counter: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    files_with_property: set[str] = set()

    ability_files = _iter_ability_files(source)

    def process(rel: str, raw_text: str) -> None:
        nonlocal samples
        if property_name not in raw_text:
            return
        try:
            data = json.loads(raw_text)
        except Exception:
            return
        file_hit = False
        for path, node in _walk(data):
            if not isinstance(node, dict):
                continue
            ntype = _node_type(node)
            prop = _property_name(node)
            hit = prop == property_name
            usage_type: str | None = None
            if hit and ntype.endswith("SetDynamicValueByProperty"):
                usage_type = "read_by_set_dynamic_value_by_property"
                dyn = _dynamic_key(node)
                if dyn:
                    dynamic_key_counter[dyn] += 1
                alias = _target_alias(node, "ReadTargetType")
                if alias:
                    target_alias_counter[f"read:{alias}"] += 1
            elif hit and ntype.endswith("StackProperty"):
                usage_type = "write_by_stack_property"
                alias = _target_alias(node, "TargetType")
                if alias:
                    target_alias_counter[f"write:{alias}"] += 1
            elif hit and "Ranges" in node and ("Property" in node or "Value" in node):
                usage_type = "watch_by_property_change"
            if usage_type:
                usage_counter[usage_type] += 1
                file_counter[rel] += 1
                file_hit = True
                mod = _modifier_name(node)
                if mod:
                    modifier_counter[mod] += 1
                if len(samples) < sample_limit:
                    samples.append({
                        "file": rel,
                        "path": path,
                        "node_type": ntype,
                        "usage_type": usage_type,
                        "property": prop,
                        "dynamic_key": _dynamic_key(node),
                        "modifier_name": mod,
                        "target_alias": _target_alias(node, "TargetType") or _target_alias(node, "ReadTargetType"),
                    })
            text = None
            # Local evidence: SetDynamicValueByProperty(Attack) and
            # SetDynamicValueByProperty(AttackConvert) often appear in the same
            # callback/template before computing a delta.  Keep this as evidence
            # only; it does not prove a formula bucket.
            if isinstance(node, dict) and hit:
                text = raw_text[path.find('/'):] if False else json.dumps(node, ensure_ascii=False)
            if text and f'"Value": "{property_name}"' in text and '"Value": "Attack"' in text:
                pair_counter["attack_and_property_same_subtree"] += 1
        if file_hit:
            files_with_property.add(rel)

    if source.zip_path:
        with zipfile.ZipFile(source.zip_path) as z:
            for rel in ability_files:
                try:
                    raw_text = z.read(source.prefix + rel).decode("utf-8", errors="ignore")
                except Exception:
                    continue
                process(rel, raw_text)
    else:
        for rel in ability_files:
            raw_text = _read_source_text(source, rel)
            if raw_text is None:
                continue
            process(rel, raw_text)

    # Conservative recommendation: any property with both reads and writes in
    # ability graphs and no direct simulator stat alias should stay engine-side.
    has_reads = usage_counter.get("read_by_set_dynamic_value_by_property", 0) > 0
    has_writes = usage_counter.get("write_by_stack_property", 0) > 0
    model = describe_engine_property(property_name).to_dict()
    if model.get("category") == "derived_flat_atk_modifier" and model.get("formula_bucket"):
        recommendation = "derived_flat_atk_modifier_model_available"
        rationale = str(model.get("reason") or "property has a simulator derived-property model")
    elif has_reads and has_writes:
        recommendation = "engine_side_property_audit_only_until_formula_bucket_proven"
        rationale = "property is read via SetDynamicValueByProperty and also written via StackProperty; it behaves as an engine-side derived property, not a plain simulator stat alias"
    else:
        recommendation = "insufficient_evidence"
        rationale = "property usage is too sparse to map safely"
    return {
        "format": "hsr_engine_property_evidence_report",
        "version": "v0.1",
        "property": property_name,
        "file_count_scanned": len(ability_files),
        "file_count_with_property": len(files_with_property),
        "usage_counts": dict(usage_counter.most_common()),
        "top_files": dict(file_counter.most_common(20)),
        "top_dynamic_keys": dict(dynamic_key_counter.most_common(20)),
        "top_modifiers": dict(modifier_counter.most_common(20)),
        "target_alias_counts": dict(target_alias_counter.most_common(20)),
        "pair_evidence_counts": dict(pair_counter.most_common()),
        "samples": samples,
        "engine_property_model": model,
        "recommendation": recommendation,
        "rationale": rationale,
        "safe_runtime_policy": {
            "set_dynamic_value_by_property": "read only if the simulator has an explicit proven property implementation; otherwise skip and audit",
            "stack_property": "preserve as property_hint / audit metadata unless mapped to a proven formula bucket",
            "formula_bucket_mapping": "do not map to atk_add/atk_pct/damage buckets without independent evidence",
        },
    }


def write_engine_property_evidence_report(tbgd_source: str | Path | TBGDSource, output_dir: str | Path, property_name: str = "AttackConvert") -> dict[str, Any]:
    report = analyze_engine_property_usage(tbgd_source, property_name=property_name)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"engine_property_{property_name}_evidence.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def analyze_engine_property_inventory(tbgd_source: str | Path | TBGDSource, *, sample_limit_per_property: int = 5) -> dict[str, Any]:
    """Scan ConfigAbility graphs and summarize all property read/write/watch usage.

    This is broader than ``analyze_engine_property_usage``: it finds property-like
    strings in SetDynamicValueByProperty, StackProperty, and property watchers so
    the runtime can prioritize which engine properties need explicit models.
    """
    source = tbgd_source if isinstance(tbgd_source, TBGDSource) else TBGDSource.open(tbgd_source)
    ability_files = _iter_ability_files(source)
    usage_by_property: dict[str, Counter[str]] = defaultdict(Counter)
    dynamic_keys_by_property: dict[str, Counter[str]] = defaultdict(Counter)
    target_alias_by_property: dict[str, Counter[str]] = defaultdict(Counter)
    files_by_property: dict[str, set[str]] = defaultdict(set)
    samples_by_property: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_sample(prop: str, rel: str, path: str, node: dict[str, Any], usage_type: str) -> None:
        if len(samples_by_property[prop]) >= sample_limit_per_property:
            return
        samples_by_property[prop].append({
            "file": rel,
            "path": path,
            "node_type": _node_type(node),
            "usage_type": usage_type,
            "property": prop,
            "dynamic_key": _dynamic_key(node),
            "target_alias": _target_alias(node, "TargetType") or _target_alias(node, "ReadTargetType"),
        })

    def process(rel: str, raw_text: str) -> None:
        try:
            data = json.loads(raw_text)
        except Exception:
            return
        for path, node in _walk(data):
            if not isinstance(node, dict):
                continue
            ntype = _node_type(node)
            prop = _property_name(node)
            usage_type: str | None = None
            if prop and ntype.endswith("SetDynamicValueByProperty"):
                usage_type = "read_by_set_dynamic_value_by_property"
                dyn = _dynamic_key(node)
                if dyn:
                    dynamic_keys_by_property[prop][dyn] += 1
                alias = _target_alias(node, "ReadTargetType")
                if alias:
                    target_alias_by_property[prop][f"read:{alias}"] += 1
            elif prop and ntype.endswith("StackProperty"):
                usage_type = "write_by_stack_property"
                alias = _target_alias(node, "TargetType")
                if alias:
                    target_alias_by_property[prop][f"write:{alias}"] += 1
            elif prop and "Ranges" in node and ("Property" in node or "Value" in node):
                usage_type = "watch_by_property_change"
            if usage_type:
                usage_by_property[prop][usage_type] += 1
                files_by_property[prop].add(rel)
                add_sample(prop, rel, path, node, usage_type)

    if source.zip_path:
        with zipfile.ZipFile(source.zip_path) as z:
            for rel in ability_files:
                try:
                    raw_text = z.read(source.prefix + rel).decode("utf-8", errors="ignore")
                except Exception:
                    continue
                process(rel, raw_text)
    else:
        for rel in ability_files:
            raw_text = _read_source_text(source, rel)
            if raw_text is not None:
                process(rel, raw_text)

    properties: list[dict[str, Any]] = []
    for prop, counts in usage_by_property.items():
        has_reads = counts.get("read_by_set_dynamic_value_by_property", 0) > 0
        has_writes = counts.get("write_by_stack_property", 0) > 0
        has_watch = counts.get("watch_by_property_change", 0) > 0
        if has_reads and has_writes:
            classification = "engine_side_property_candidate"
        elif has_reads and not has_writes:
            classification = "read_only_property_candidate"
        elif has_writes and not has_reads:
            classification = "write_only_property_candidate"
        else:
            classification = "watch_only_property_candidate" if has_watch else "unknown_property_candidate"
        properties.append({
            "property": prop,
            "classification": classification,
            "engine_property_model": describe_engine_property(prop).to_dict(),
            "usage_counts": dict(counts.most_common()),
            "file_count": len(files_by_property[prop]),
            "top_dynamic_keys": dict(dynamic_keys_by_property[prop].most_common(10)),
            "target_alias_counts": dict(target_alias_by_property[prop].most_common(10)),
            "samples": samples_by_property[prop],
        })
    properties.sort(key=lambda r: (-(sum(r["usage_counts"].values())), r["property"]))
    class_counts = Counter(p["classification"] for p in properties)
    formula_ready = []
    engine_derived = []
    derived_model_ready = []
    unknown_write_heavy = []
    for row in properties:
        model = row.get("engine_property_model") if isinstance(row.get("engine_property_model"), dict) else {}
        usage_total = sum(row.get("usage_counts", {}).values())
        usage = dict(row.get("usage_counts", {}))
        item = {
            "property": row.get("property"),
            "classification": row.get("classification"),
            "usage_total": usage_total,
            "usage_counts": usage,
            "formula_bucket": model.get("formula_bucket"),
            "model_category": model.get("category"),
            "reason": model.get("reason"),
        }
        if model.get("category") == "formula_bucket_property_hint" and usage.get("write_by_stack_property", 0) > 0:
            formula_ready.append(item)
        elif model.get("category") == "derived_flat_atk_modifier" and model.get("formula_bucket"):
            derived_model_ready.append(item)
        elif model.get("category") == "engine_derived_property":
            engine_derived.append(item)
        elif row.get("classification") in {"write_only_property_candidate", "engine_side_property_candidate"} and not model.get("formula_bucket"):
            unknown_write_heavy.append(item)
    formula_ready.sort(key=lambda x: (-int(x.get("usage_total") or 0), str(x.get("property"))))
    engine_derived.sort(key=lambda x: (-int(x.get("usage_total") or 0), str(x.get("property"))))
    derived_model_ready.sort(key=lambda x: (-int(x.get("usage_total") or 0), str(x.get("property"))))
    unknown_write_heavy.sort(key=lambda x: (-int(x.get("usage_total") or 0), str(x.get("property"))))
    return {
        "format": "hsr_engine_property_inventory_report",
        "version": "v0.2",
        "file_count_scanned": len(ability_files),
        "property_count": len(properties),
        "classification_counts": dict(class_counts.most_common()),
        "prioritization": {
            "formula_bucket_ready_count": len(formula_ready),
            "engine_derived_audit_count": len(engine_derived),
            "derived_model_ready_count": len(derived_model_ready),
            "unknown_write_heavy_count": len(unknown_write_heavy),
            "formula_bucket_ready_top": formula_ready[:20],
            "derived_model_ready_top": derived_model_ready[:20],
            "engine_derived_audit_top": engine_derived[:20],
            "unknown_write_heavy_top": unknown_write_heavy[:20],
        },
        "properties": properties,
    }


def write_engine_property_inventory_report(tbgd_source: str | Path | TBGDSource, output_dir: str | Path) -> dict[str, Any]:
    report = analyze_engine_property_inventory(tbgd_source)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "engine_property_inventory.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

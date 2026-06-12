from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
import json

ELEMENT_BREAK_MULTIPLIERS = {
    "physical": 2.0,
    "fire": 2.0,
    "wind": 1.5,
    "ice": 1.0,
    "thunder": 1.0,
    "lightning": 1.0,
    "quantum": 0.5,
    "imaginary": 0.5,
}

_ELEMENT_ALIASES = {
    "lightning": "thunder",
    "electric": "thunder",
    "imaginary": "imaginary",
    "physical": "physical",
    "fire": "fire",
    "ice": "ice",
    "wind": "wind",
    "quantum": "quantum",
    "thunder": "thunder",
}

@lru_cache(maxsize=1)
def _break_base_table() -> dict[int, float]:
    p = Path(__file__).with_name("data") / "break_base_damage.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {int(k): float(v) for k, v in data.items()}
    except Exception:
        # Minimal fallback from AvatarBreakDamage; 80 is the common combat level.
        return {80: 3767.5535}


def normalize_break_element(element: Any) -> str:
    e = str(element or "").strip().lower()
    return _ELEMENT_ALIASES.get(e, e)


def break_base_damage(level: Any) -> float:
    table = _break_base_table()
    try:
        lvl = int(float(level))
    except Exception:
        lvl = 80
    if lvl in table:
        return table[lvl]
    if not table:
        return 3767.5535
    # Clamp outside known table and linearly interpolate between nearest known levels.
    keys = sorted(table)
    if lvl <= keys[0]:
        return table[keys[0]]
    if lvl >= keys[-1]:
        return table[keys[-1]]
    lo = max(k for k in keys if k <= lvl)
    hi = min(k for k in keys if k >= lvl)
    if lo == hi:
        return table[lo]
    return table[lo] + (table[hi] - table[lo]) * ((lvl - lo) / (hi - lo))


def element_break_multiplier(element: Any) -> float:
    return ELEMENT_BREAK_MULTIPLIERS.get(normalize_break_element(element), 1.0)


def toughness_units(max_toughness: Any) -> float:
    try:
        val = float(max_toughness)
    except Exception:
        val = 0.0
    # HSR data commonly stores one basic-attack unit as 30 toughness.
    return max(0.0, val) / 30.0

def max_toughness_multiplier(max_toughness: Any) -> float:
    """HSR weakness-break max-toughness multiplier.

    Public formula tables usually write this as 0.5 + toughness_units/4,
    where one basic toughness unit is 30 in the current data model.  For a
    120 toughness target this gives 1.5, matching earlier hand checks.
    """
    return 0.5 + toughness_units(max_toughness) / 4.0


def break_dot_base_damage(kind: Any, *, level: Any, max_toughness: Any = 0, max_hp: Any = 0, elite_or_boss: bool = False, stacks: Any = 1) -> tuple[float, dict[str, Any]]:
    """Return base damage for Weakness Break aftermath effects before BE/DEF/RES.

    Supported aftermath kinds follow public HSR weakness-break tables:
    - bleed: min(16% normal max HP / 7% elite-boss max HP, physical cap)
    - burn: 1 * level multiplier
    - shock: 2 * level multiplier
    - wind_shear: 1 * stack_count * level multiplier
    - freeze_thaw: 1 * level multiplier
    - entanglement: 0.6 * stack_count * level multiplier * max toughness multiplier
    """
    k = str(kind or '').lower()
    base = break_base_damage(level)
    mtm = max_toughness_multiplier(max_toughness)
    st = max(1, int(float(stacks or 1)))
    audit: dict[str, Any] = {
        'kind': k, 'level': int(float(level or 80)), 'level_multiplier': base,
        'max_toughness': float(max_toughness or 0), 'max_toughness_multiplier': mtm,
        'stacks': st, 'elite_or_boss': bool(elite_or_boss),
    }
    if k == 'bleed':
        hp = max(0.0, float(max_hp or 0.0))
        hp_ratio = 0.07 if elite_or_boss else 0.16
        uncapped = hp * hp_ratio
        cap = 2.0 * base * mtm
        audit.update({'hp_ratio': hp_ratio, 'uncapped': uncapped, 'cap': cap})
        return min(uncapped, cap), audit
    if k == 'burn':
        return 1.0 * base, audit
    if k in {'shock', 'lightning_shock'}:
        return 2.0 * base, audit
    if k in {'wind_shear', 'windshear'}:
        return 1.0 * st * base, audit
    if k in {'freeze_thaw', 'freeze'}:
        return 1.0 * base, audit
    if k == 'entanglement':
        return 0.6 * st * base * mtm, audit
    return 0.0, {**audit, 'unsupported': True}


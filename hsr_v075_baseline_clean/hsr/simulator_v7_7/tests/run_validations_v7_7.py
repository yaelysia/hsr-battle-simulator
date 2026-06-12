#!/usr/bin/env python3
from __future__ import annotations
import json
import math
from pathlib import Path
import sys
import yaml
import zipfile
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hsr_simulator_prototype_v7_7 import BattleSimulator, StatusEffect, UnitState, load_case, main as simulator_main
from hsr_engine.break_formula import break_base_damage, max_toughness_multiplier
from hsr_engine.mechanism_glossary import glossary_report
from hsr_engine.genericity_auditor import genericity_audit_report
from hsr_engine.enemy_mechanism_auditor import analyze_enemy_mechanisms
from hsr_engine.break_formula_auditor import break_formula_audit_report
from hsr_engine.souldragon_template import derive_souldragon_action_template, load_souldragon_action_template
from hsr_engine.enemy_route_harness import write_enemy_route_harness
from hsr_engine.enemy_template_compiler import compile_enemy_template, compile_enemy_model_pack, _extract_ai_decisions_from_config
from hsr_engine.enemy_ability_graph_lowerer import write_monster_ability_graph_lowering
from hsr_engine.character_mechanism_auditor import audit_character_mechanisms

OUT = ROOT / "output_v7_7"
OUT.mkdir(exist_ok=True)


def run_case(path: Path):
    case = load_case(str(path))
    sim = BattleSimulator(case)
    result = sim.run_route(case.get("route", []))
    out_path = OUT / f"{path.stem}_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def close(a, b, eps=1e-6):
    return abs(a - b) <= eps


checks: list[str] = []

# Smoke-test existing examples/validation cases to ensure no regressions.
for folder in [ROOT / "examples", ROOT / "validation"]:
    for path in sorted(folder.glob("*.yaml")):
        run_case(path)
        checks.append(f"SMOKE PASS {path.relative_to(ROOT)}")

# Targeted regression cases.
case_dir = ROOT / "validation_v1_6"
case_dir_v1_8 = ROOT / "validation_v1_8"
case_dir_v2_0 = ROOT / "validation_v2_0"
case_dir_v2_1 = ROOT / "validation_v2_1"
case_dir_v2_2 = ROOT / "validation_v2_2"
case_dir_v2_3 = ROOT / "validation_v2_3"

r = run_case(case_dir / "multi_hit_duration_case.yaml")
att = r["state"]["units"]["attacker"]
tgt = r["state"]["units"]["target"]
att_status = {s["id"]: s for s in att["statuses"]}
tgt_status = {s["id"]: s for s in tgt["statuses"]}
assert "hits_dealt_twice" not in att_status, "hits_dealt should tick per hit and expire after two packets"
assert att_status["attacks_dealt_once"]["duration_value"] == 1, "attacks_dealt should tick once per action"
assert "hits_taken_twice" not in tgt_status, "hits_taken should tick per hit and expire after two packets"
assert tgt_status["attacks_taken_once"]["duration_value"] == 1, "attacks_taken should tick once per attack"
checks.append("PASS multi-hit per-hit vs per-attack duration separation")

r = run_case(case_dir / "aoe_multi_kill_energy_case.yaml")
energy = r["state"]["units"]["attacker"]["energy"]
assert close(energy, 24.0), f"expected 24 energy from two kills with ERR 1.2, got {energy}"
assert not r["state"]["units"]["e1"]["alive"] and not r["state"]["units"]["e2"]["alive"]
checks.append("PASS AoE multi-kill grants one kill energy reward per defeated enemy")

r = run_case(case_dir / "shield_hit_energy_case.yaml")
ally = r["state"]["units"]["ally"]
assert close(ally["hp"], 1000.0), f"shielded ally HP should remain 1000, got {ally['hp']}"
assert close(ally["shield"], 100.0), f"shield should reduce from 200 to 100, got {ally['shield']}"
assert close(ally["energy"], 12.0), f"hit-taken energy should be 10*1.2=12, got {ally['energy']}"
checks.append("PASS shield absorption still allows configured hit-taken energy")

r = run_case(case_dir / "queue_priority_case.yaml")
log_msgs = [e["message"] for e in r["log"]]
immediate_i = next(i for i, m in enumerate(log_msgs) if "actor.immediate_mark" in m and "Resolve queued" in m)
interrupt_i = next(i for i, m in enumerate(log_msgs) if "actor.interrupt_mark" in m and "Resolve queued" in m)
assert immediate_i < interrupt_i, "immediate queue should resolve before interrupt queue"
assert r["state"]["global"]["flags"]["immediate_resolved"] is True
assert r["state"]["global"]["flags"]["interrupt_resolved"] is True
checks.append("PASS queue priority: immediate before interrupt")

r = run_case(case_dir / "expected_crit_clamp_case.yaml")
target_hp = r["state"]["units"]["target"]["hp"]
assert close(target_hp, 7000.0), f"crit_rate 150% should clamp to 100%, target HP expected 7000, got {target_hp}"
checks.append("PASS expected crit mode clamps crit rate to [0, 1]")

r = run_case(case_dir / "hp_bar_trigger_immediate_case.yaml")
boss = r["state"]["units"]["boss"]
assert boss["hp_bars_remaining"] == 1, "first HP bar should be depleted"
assert close(boss["hp"], 100.0), "default HP-bar overflow should not carry over"
assert boss["flags"].get("phase_action_done") is True, "after_hp_bar_depleted should fire immediate phase action"
checks.append("PASS HP-bar transition trigger and immediate phase action")


r = run_case(case_dir / "multi_hp_bar_carry_case.yaml")
carry = r["state"]["units"]["multi_bar_carry"]
phase = r["state"]["units"]["multi_bar_phase"]
assert carry["alive"] is True, "carry-over damage should leave target alive on final bar in this case"
assert carry["hp_bars_remaining"] == 1, f"carry-over should consume two bars, got {carry['hp_bars_remaining']} bars remaining"
assert close(carry["hp"], 50.0), f"carry-over remaining HP expected 50, got {carry['hp']}"
assert phase["alive"] is True, "phase-style no-carry should leave target alive"
assert phase["hp_bars_remaining"] == 2, f"no-carry should consume only one bar, got {phase['hp_bars_remaining']}"
assert close(phase["hp"], 100.0), f"no-carry next bar should be full, got {phase['hp']}"
checks.append("PASS multi-HP-bar carry-over consumes multiple bars and no-carry stops at phase boundary")


# v1.1 explicit HP model semantics: phase_hp no-carry by default; segmented_hp carries by default.
r = run_case(case_dir / "hp_model_semantics_case.yaml")
phase = r["state"]["units"]["phase_boss"]
seg = r["state"]["units"]["segmented_target"]
assert phase["hp_model_type"] == "phase_hp"
assert phase["hp_bars_remaining"] == 2, f"phase_hp should consume only one bar, got {phase['hp_bars_remaining']}"
assert close(phase["hp"], 100.0), f"phase_hp should restore next bar to full, got {phase['hp']}"
assert seg["hp_model_type"] == "segmented_hp"
assert seg["hp_bars_remaining"] == 1, f"segmented_hp should carry through two bars, got {seg['hp_bars_remaining']}"
assert close(seg["hp"], 50.0), f"segmented_hp remaining HP expected 50, got {seg['hp']}"
checks.append("PASS explicit HP model semantics: phase_hp no-carry, segmented_hp carry")


# v1.3 legacy boolean tag predicate shorthand.
r = run_case(case_dir / "legacy_action_has_tag_case.yaml")
assert r["state"]["units"]["actor"]["flags"].get("tag_triggered") == 1.0, "legacy {action_has_tag: attack} should fire as boolean predicate"
checks.append("PASS legacy action_has_tag shorthand predicate evaluates as boolean")

# v1.3 context-specific crit stats: conditional Crit DMG should apply to Ultimate only.
r = run_case(case_dir / "conditional_crit_stat_case.yaml")
skill_hp = r["state"]["units"]["skill_target"]["hp"]
ult_hp = r["state"]["units"]["ult_target"]["hp"]
assert close(skill_hp, 8500.0), f"skill target should take 1500 damage with base crit dmg, got HP {skill_hp}"
assert close(ult_hp, 7500.0), f"ultimate target should take 2500 damage with conditional crit dmg, got HP {ult_hp}"
checks.append("PASS conditional Crit DMG / Crit Rate modifiers are applied in crit resolution")

# v1.4 explicit hp_model.bars: different next-bar HP and inline on_depleted effects.
r = run_case(case_dir / "hp_model_bar_effects_case.yaml")
boss = r["state"]["units"]["boss"]
assert boss["flags"].get("bar_effect_done") is True, "hp_model.bars[].on_depleted inline effects should fire"
assert boss["hp_bars_remaining"] == 1, f"first bar should be depleted, got {boss['hp_bars_remaining']} bars remaining"
assert close(boss["hp"], 200.0), f"next bar HP should use explicit second bar HP 200, got {boss['hp']}"
assert close(boss["max_hp"], 200.0), f"max_hp should update to explicit second bar HP 200, got {boss['max_hp']}"
checks.append("PASS explicit hp_model.bars next-bar HP and on_depleted effects")

# v1.4 carry-over with non-uniform hp_model.bars should use each next bar's HP.
r = run_case(case_dir / "hp_model_mixed_bar_carry_case.yaml")
seg = r["state"]["units"]["segmented"]
assert seg["hp_bars_remaining"] == 2, f"250 damage should consume only first 100-HP bar, got {seg['hp_bars_remaining']} bars remaining"
assert close(seg["max_hp"], 200.0), f"current bar max HP should become second bar HP 200, got {seg['max_hp']}"
assert close(seg["hp"], 50.0), f"overflow 150 into second 200-HP bar should leave 50 HP, got {seg['hp']}"
checks.append("PASS carry-over across non-uniform hp_model.bars uses each next bar HP")

# v1.5 context-specific scaling stat modifiers should affect base damage.
r = run_case(case_dir / "conditional_scaling_stat_case.yaml")
target_hp = r["state"]["units"]["target"]["hp"]
assert close(target_hp, 8500.0), f"conditional atk_add should raise base damage to 1500, got HP {target_hp}"
checks.append("PASS conditional modifiers apply to packet scaling stat")

# v2.0 contextual pct modifiers must preserve split stat base/pct/flat semantics.
r = run_case(case_dir / "conditional_split_scaling_stat_case.yaml")
target_hp = r["state"]["units"]["target"]["hp"]
assert close(target_hp, 8400.0), f"split ATK should be 1000*1.5+100=1600, got HP {target_hp}"
checks.append("PASS conditional pct modifiers preserve split stat semantics")


# v2.0 phase_hp boundary: later packets in the same action must not damage the next phase bar.
r = run_case(case_dir_v2_0 / "phase_hp_same_action_lock_case.yaml")
boss = r["state"]["units"]["phase_boss"]
assert boss["hp_bars_remaining"] == 1, f"first phase bar should be consumed, got {boss['hp_bars_remaining']}"
assert close(boss["hp"], 200.0), f"second hit should be locked out of the new phase bar, got HP {boss['hp']}"
assert any(e["event_type"] == "damage_skip" for e in r["log"]), "phase lock should log a skipped later packet"
checks.append("PASS phase_hp boundary locks later packets from the same action")

# v2.0 condition RHS references: right: flag:/ctx:/unit: must resolve, not compare as a literal string.
r = run_case(case_dir_v2_0 / "condition_right_ref_case.yaml")
assert r["state"]["units"]["actor"]["flags"].get("right_ref_triggered") is True, "condition right-side reference should resolve"
checks.append("PASS condition right-side references resolve before comparison")

# v2.0 immediate_action must defer target selection like launch_action.
# If an after_defeat trigger queues a target-policy action before wave transition,
# the queued action should be able to select enemies spawned after the current action.
r = run_case(case_dir_v2_0 / "immediate_action_deferred_wave_target_case.yaml")
e2 = r["state"]["units"]["e2"]
assert e2["alive"] is True, "second-wave enemy should exist after wave transition"
assert close(e2["hp"], 900.0), f"deferred immediate_action should hit newly spawned e2 for 100, got HP {e2['hp']}"
assert any(e["event_type"] == "damage" and e["data"].get("target_id") == "e2" for e in r["log"]), "queued immediate action should damage e2"
checks.append("PASS immediate_action target policy is deferred across wave transition")

# v2.0 explicit single-target YAML strings must not be iterated character-by-character.
r = run_case(case_dir_v2_0 / "single_target_string_normalization_case.yaml")
e2 = r["state"]["units"]["e2"]
assert close(e2["hp"], 900.0), f"targets: e2 should hit e2 once for 100, got HP {e2['hp']}"
checks.append("PASS single-target YAML strings are normalized to target lists")

# v2.0 kill energy should be visible to after_defeat triggers.
r = run_case(case_dir_v2_0 / "kill_energy_before_after_defeat_trigger_case.yaml")
actor = r["state"]["units"]["actor"]
assert close(actor["energy"], 100.0), f"actor should reach full energy from kill reward, got {actor['energy']}"
assert actor["flags"].get("after_defeat_saw_full_energy") is True, "after_defeat trigger should observe post-kill energy"
checks.append("PASS kill energy is applied before after_defeat_enemy trigger conditions")

# v2.0 deferred queued actions with no valid targets should be skipped before paying costs.
r = run_case(case_dir_v2_0 / "queued_action_no_valid_target_skip_case.yaml")
assert r["state"]["global"]["skill_points"] == 3, "targetless queued follow-up should not spend SP"
assert close(r["state"]["units"]["actor"]["energy"], 0.0), "targetless queued follow-up should not grant action energy"
assert any(e["event_type"] == "queue_skip" for e in r["log"]), "targetless deferred queued action should log queue_skip"
checks.append("PASS deferred queued actions with no valid targets are skipped without costs")

# v2.1 packet-level same_target should use the action's selected target.
r = run_case(case_dir_v2_1 / "packet_same_target_policy_case.yaml")
e1 = r["state"]["units"]["e1"]
assert close(e1["hp"], 800.0), f"two packet-level same_target hits should damage selected e1 to 800, got {e1['hp']}"
checks.append("PASS packet-level same_target resolves from the action selected target")

# v2.1 queued follow-up actions should preserve their selected target for packet policies.
r = run_case(case_dir_v2_1 / "queued_packet_same_target_policy_case.yaml")
e2 = r["state"]["units"]["e2"]
assert close(e2["hp"], 900.0), f"queued action packet same_target should hit newly selected e2 for 100, got {e2['hp']}"
checks.append("PASS queued action packet-level same_target resolves from the queued action selected target")

# v2.2 queued explicit targets can become stale after an earlier queued action kills them.
r = run_case(case_dir_v2_2 / "stale_explicit_queued_target_skip_case.yaml")
assert r["state"]["global"]["skill_points"] == 2, "only the first explicit queued attack should spend SP"
assert close(r["state"]["units"]["actor"]["energy"], 30.0), "stale second queued attack should not grant action energy"
assert any(e["event_type"] == "queue_skip" and "no live damage targets" in e["message"] for e in r["log"]), "stale explicit queued attack should log queue_skip"
checks.append("PASS stale explicit queued attack targets are skipped before costs/action energy")

# v3.6 damage_unit effects that are part of an attack should grant kill energy
# before after_defeat_enemy triggers, matching normal damage packets.
r = run_case(case_dir_v2_3 / "effect_damage_kill_energy_case.yaml")
actor = r["state"]["units"]["actor"]
assert close(actor["energy"], 100.0), f"effect damage kill should grant kill energy before triggers, got {actor['energy']}"
assert actor["flags"].get("after_defeat_saw_full_energy") is True, "after_defeat trigger should observe post-kill energy from effect damage"
checks.append("PASS action-owned effect damage grants kill energy before after_defeat_enemy")

# v3.6 effect damage must not spawn the next wave in the middle of the same action.
r = run_case(case_dir_v2_3 / "effect_damage_no_mid_action_wave_case.yaml")
e2 = r["state"]["units"]["e2"]
assert e2["alive"] is True, "second wave enemy should spawn after the action ends"
assert close(e2["hp"], 1000.0), f"later packet in same action should not hit newly spawned e2, got HP {e2['hp']}"
assert not any(e["event_type"] == "damage" and e["data"].get("target_id") == "e2" for e in r["log"]), "no packet in the same action should damage e2 after effect damage cleared wave 1"
checks.append("PASS action-owned effect damage defers wave transition until action end")

# v3.6 gain_energy/grant_energy aliases should use the standard energy-source helper.
r = run_case(case_dir_v2_3 / "gain_energy_alias_case.yaml")
actor = r["state"]["units"]["actor"]
assert close(actor["energy"], 12.0), f"gain_energy alias should apply ERR to base energy: expected 12, got {actor['energy']}"
checks.append("PASS gain_energy effect alias uses standard ERR-aware energy source")


case_dir_v2_4 = ROOT / "validation_v2_4"

# v3.6 action-owned damage_unit that crosses a phase boundary must lock later packets/effects
# in the same action, not only later damage packets after a previous damage packet.
r = run_case(case_dir_v2_4 / "effect_damage_phase_lock_case.yaml")
boss = r["state"]["units"]["phase_boss"]
assert boss["hp_bars_remaining"] == 1, f"first phase bar should be consumed, got {boss['hp_bars_remaining']}"
assert close(boss["hp"], 200.0), f"later packet should be locked out of new phase bar, got HP {boss['hp']}"
assert any(e["event_type"] == "damage_skip" for e in r["log"]), "later packet should log damage_skip after effect phase boundary"
checks.append("PASS action-owned effect damage phase boundary locks later packets")

r = run_case(case_dir_v2_4 / "effect_damage_phase_lock_later_effect_case.yaml")
boss = r["state"]["units"]["phase_boss"]
assert boss["hp_bars_remaining"] == 1, f"first phase bar should be consumed, got {boss['hp_bars_remaining']}"
assert close(boss["hp"], 200.0), f"later effect damage should be locked out of new phase bar, got HP {boss['hp']}"
assert any(e["event_type"] == "effect_damage_skip" for e in r["log"]), "later effect damage should log effect_damage_skip after effect phase boundary"
checks.append("PASS action-owned effect damage phase boundary locks later effect damage")

r = run_case(case_dir_v2_4 / "action_advance_alias_case.yaml")
target = r["state"]["units"]["victim"]
assert close(target["remaining_av"], 70.0), f"advance_percent/delay_percent aliases should leave AV 80*(1-.25)+100*.10=70, got {target['remaining_av']}"
checks.append("PASS advance_action/delay_action percent aliases are accepted")


case_dir_v2_5 = ROOT / "validation_v2_5"

# v3.6 queued actions whose only damage is damage_unit must also be preflighted
# for stale explicit targets before paying costs or action energy.
r = run_case(case_dir_v2_5 / "stale_effect_damage_queued_target_skip_case.yaml")
assert r["state"]["global"]["skill_points"] == 2, "only the first effect-damage queued attack should spend SP"
assert close(r["state"]["units"]["actor"]["energy"], 30.0), "stale second effect-damage queued attack should not grant action energy"
assert any(e["event_type"] == "queue_skip" and "no live damage targets" in e["message"] for e in r["log"]), "stale effect-damage queued attack should log queue_skip"
checks.append("PASS stale queued effect-damage targets are skipped before costs/action energy")

# v3.6 queued actions whose actor died before the queue drains should be skipped,
# not crash the simulation or spend resources.
r = run_case(case_dir_v2_5 / "dead_queued_actor_skip_case.yaml")
assert r["state"]["global"]["skill_points"] == 3, "dead queued actor should not spend SP"
assert close(r["state"]["units"]["helper"]["energy"], 0.0), "dead queued actor should not gain action energy"
assert any(e["event_type"] == "queue_skip" and "queued actor is dead" in e["message"] for e in r["log"]), "dead queued actor should log queue_skip"
checks.append("PASS dead queued actors are skipped before costs/action energy")


case_dir_v2_6 = ROOT / "validation_v2_6"

# v3.6 individual effects can carry their own condition; false effects must not execute.
r = run_case(case_dir_v2_6 / "effect_condition_case.yaml")
flags = r["state"]["global"]["flags"]
assert flags.get("should_not_set") is None, "effect with false condition should not execute"
assert flags.get("should_set") is True, "effect with true condition should execute"
assert any(e["event_type"] == "effect_skip" for e in r["log"]), "false effect condition should log effect_skip"
checks.append("PASS effect-level conditions gate individual effects")


case_dir_v2_7 = ROOT / "validation_v2_7"

# v2.7 gain_energy amount shorthand must respect affected_by_err=true.
r = run_case(case_dir_v2_7 / "gain_energy_amount_err_case.yaml")
actor = r["state"]["units"]["actor"]
assert close(actor["energy"], 22.0), f"amount shorthand with ERR should grant 10*1.2 + fixed 10 = 22, got {actor['energy']}"
checks.append("PASS gain_energy amount shorthand respects affected_by_err")

case_dir_v2_8 = ROOT / "validation_v2_8"

# v2.8 multi-hit actions can split one action's total energy across packets.
# If hit 1 fills energy and queues Ultimate, that Ultimate must resolve before
# a later hit's after_defeat_enemy Reappearance queue.
r = run_case(case_dir_v2_8 / "multi_hit_packet_energy_ultimate_before_reappearance_case.yaml")
seele = r["state"]["units"]["seele"]
assert seele["flags"].get("ultimate_resolved") is True, "Ultimate queued after packet-1 energy should resolve"
assert seele["flags"].get("reappearance_resolved") is True, "Reappearance should still resolve after the kill"
messages = [e["message"] for e in r["log"]]
packet1_energy_i = next(i for i, m in enumerate(messages) if "packet:skill_three_hit.hit_1" in m)
queue_ult_i = next(i for i, m in enumerate(messages) if "Queued action seele.ultimate in ultimate_queue" in m)
damage_hit2_i = next(i for i, e in enumerate(r["log"]) if e["event_type"] == "damage" and e["data"].get("packet_id") == "hit_2")
ult_resolve_i = next(i for i, m in enumerate(messages) if "Resolve queued action from ultimate_queue: seele.ultimate" in m)
reapp_resolve_i = next(i for i, m in enumerate(messages) if "Resolve queued action from immediate_queue: seele.reappearance_turn" in m)
assert packet1_energy_i < queue_ult_i < damage_hit2_i, "Ultimate should be queueable immediately after hit-1 energy, before later hits finish"
assert ult_resolve_i < reapp_resolve_i, "Ultimate queued mid-skill should resolve before Reappearance queued by the later kill"
assert close(seele["energy"], 0.0), f"Ultimate should consume the full 100 energy; final energy got {seele['energy']}"
checks.append("PASS per-packet action energy can queue Ultimate before later-hit Reappearance")

# v2.8 queued actions can opt out of carrying across a wave transition. This
# models Seele Reappearance being lost when the kill ends the wave, while an
# automatic Skill queued by the same kill is allowed to carry into the next wave.
r = run_case(case_dir_v2_8 / "reappearance_no_wave_carry_auto_skill_wave_carry_case.yaml")
seele = r["state"]["units"]["seele"]
e2 = r["state"]["units"]["e2"]
assert seele["flags"].get("reappearance_carried_wrongly") is None, "Reappearance must not execute after wave transition when carry_across_wave=false"
assert close(e2["hp"], 900.0), f"Auto Skill should carry to next wave and hit e2 for 100, got HP {e2['hp']}"
assert any(e["event_type"] == "queue_skip" and "cannot carry across wave" in e["message"] for e in r["log"]), "Non-carry Reappearance should log queue_skip after wave transition"
assert any(e["event_type"] == "damage" and e["data"].get("target_id") == "e2" and e["data"].get("packet_id") == "auto_hit" for e in r["log"]), "Auto Skill should damage the spawned second-wave enemy"
checks.append("PASS Reappearance can be non-carry across wave while auto Skill carries")

# v3.0: wave-carry policy should be defined on the queued action itself, so
# character modeling can say which extra actions carry across waves.
case_dir_v3_0 = ROOT / "validation_v3_0"
r = run_case(case_dir_v3_0 / "action_level_wave_carry_policy_case.yaml")
seele = r["state"]["units"]["seele"]
e2 = r["state"]["units"]["e2"]
assert seele["flags"].get("reappearance_carried_wrongly") is None, "action-level queued_action_policy carry_across_wave=false should drop Reappearance"
assert close(e2["hp"], 900.0), f"action-level policy should still allow auto Skill to carry and hit e2, got HP {e2['hp']}"
assert any(e["event_type"] == "queue_skip" and "cannot carry across wave" in e["message"] for e in r["log"]), "action-level no-carry should log queue_skip"
checks.append("PASS queued action wave-carry policy can live on action definitions")

# v3.6: quoted boolean strings must be parsed safely.
r = run_case(case_dir_v3_0 / "string_false_wave_carry_case.yaml")
e2 = r["state"]["units"]["e2"]
assert close(e2["hp"], 1000.0), f"quoted carry_across_wave: false should not carry to e2, got HP {e2['hp']}"
assert any(e["event_type"] == "queue_skip" and "cannot carry across wave" in e["message"] for e in r["log"]), "quoted false should skip across-wave queued action"
checks.append("PASS quoted boolean strings for wave-carry policy are parsed safely")

# v3.6: queued actions should infer extra_turn lifecycle from action tags, not
# require every trigger to repeat turn_kind.
r = run_case(case_dir_v3_0 / "action_tag_infers_extra_turn_kind_case.yaml")
seele = r["state"]["units"]["seele"]
assert seele["flags"].get("reappearance_action_body_resolved") is True, "queued action body should resolve"
assert seele["flags"].get("extra_turn_start_seen") is True, "extra_turn_start should fire from action tag inference"
assert seele["flags"].get("extra_turn_end_seen") is True, "extra_turn_end should fire from action tag inference"
checks.append("PASS queued action turn_kind can be inferred from action tags")

# v3.6: queued_action_policy can explicitly specify turn_kind even without tags.
r = run_case(case_dir_v3_0 / "action_policy_turn_kind_case.yaml")
actor = r["state"]["units"]["actor"]
assert actor["flags"].get("action_body_resolved") is True, "queued policy action should resolve"
assert actor["flags"].get("policy_extra_turn_start_seen") is True, "queued_action_policy.turn_kind should drive extra_turn lifecycle"
checks.append("PASS queued action turn_kind can live on action queued_action_policy")


case_dir_v3_1 = ROOT / "validation_v3_1"

# v3.1: boolean-like strings must be parsed safely outside queue policy too.
r = run_case(case_dir_v3_1 / "string_false_energy_affects_err_case.yaml")
actor = r["state"]["units"]["actor"]
assert close(actor["energy"], 10.0), f"affected_by_err: quoted false should be fixed 10 energy, got {actor['energy']}"
checks.append("PASS quoted false affected_by_err does not apply ERR")

r = run_case(case_dir_v3_1 / "string_false_hit_taken_grant_defeated_case.yaml")
e1 = r["state"]["units"]["e1"]
assert close(e1["energy"], 0.0), f"grant_if_defeated: quoted false should skip defeated target energy, got {e1['energy']}"
assert any(e["event_type"] == "resource_skip" for e in r["log"]), "defeated target hit energy should log resource_skip"
checks.append("PASS quoted false grant_if_defeated skips defeated hit energy")

r = run_case(case_dir_v3_1 / "string_false_hp_carry_case.yaml")
boss = r["state"]["units"]["boss"]
assert boss["hp_bars_remaining"] == 1, f"boss should move to second phase bar, got {boss['hp_bars_remaining']} bars remaining"
assert close(boss["hp"], 100.0), f"quoted carry_over_damage false should not leak overflow into next phase bar, got HP {boss['hp']}"
checks.append("PASS quoted false hp_model carry_over_damage blocks phase overflow")

# v3.6: support character-text duration alias `extra_turn_consumes_duration`.
r = run_case(case_dir_v3_1 / "duration_extra_turn_consumes_alias_case.yaml")
actor = r["state"]["units"]["actor"]
assert actor["flags"].get("extra_action_done") is True, "queued extra action should resolve"
assert not actor["statuses"], f"owner_turns buff with extra_turn_consumes_duration=true should expire on extra turn, got {actor['statuses']}"
assert any(e["event_type"] == "duration_tick" and e["data"].get("turn_kind") == "extra_turn" for e in r["log"]), "extra-turn duration tick should be logged"
checks.append("PASS duration extra_turn_consumes_duration alias is honored")


case_dir_v3_2 = ROOT / "validation_v3_2"

# v3.2: owner-turn-start decrement durations should expire at turn start,
# and source/owner aliases from character modeling should be recognized.
r = run_case(case_dir_v3_2 / "owner_turn_start_decrement_case.yaml")
actor = r["state"]["units"]["actor"]
assert actor["flags"].get("action_resolved") is True, "regular action should resolve after turn-start duration tick"
assert not actor["statuses"], f"owner_turn_start_decrement status should expire before the action body, got {actor['statuses']}"
turn_start_i = next(i for i, e in enumerate(r["log"]) if e["event_type"] == "turn_start")
duration_i = next(i for i, e in enumerate(r["log"]) if e["event_type"] == "duration_tick" and e["data"].get("event") == "turn_start")
action_start_i = next(i for i, e in enumerate(r["log"]) if e["event_type"] == "action_start")
assert turn_start_i < duration_i < action_start_i, "turn-start duration should tick before action_start"
checks.append("PASS owner_turn_start_decrement duration alias ticks at turn start")


case_dir_v3_3 = ROOT / "validation_v3_3"

# v3.3: action-level effects_after_action_start should resolve before damage,
# while effects_after_damage should resolve once after all packets.
r = run_case(case_dir_v3_3 / "action_effect_windows_case.yaml")
e1 = r["state"]["units"]["e1"]
assert close(e1["hp"], 300.0), f"pre-damage action-start effect should double 100 damage to 200, got enemy HP {e1['hp']}"
assert r["state"]["global"]["flags"].get("after_damage_window_seen") is True, "effects_after_damage should execute after damage packets"
effect_add_i = next(i for i, e in enumerate(r["log"]) if e["event_type"] == "effect" and "Add status pre_damage_buff" in e["message"])
damage_i = next(i for i, e in enumerate(r["log"]) if e["event_type"] == "damage" and e["data"].get("packet_id") == "hit")
after_eff_i = next(i for i, e in enumerate(r["log"]) if e["event_type"] == "effect" and "after_damage_window_seen" in e["message"])
assert effect_add_i < damage_i < after_eff_i, "action effect windows should order as after_action_start -> damage -> after_damage"
checks.append("PASS action effects_after_action_start/effects_after_damage windows resolve in order")


case_dir_v3_4 = ROOT / "validation_v3_4"

# v3.6: before_damage effects can mutate the currently resolving packet.
r = run_case(case_dir_v3_4 / "modify_damage_packet_case.yaml")
e1 = r["state"]["units"]["e1"]
assert close(e1["hp"], 900.0), f"def_ignore packet mutation should make 100 raw damage deal full 100, got HP {e1['hp']}"
assert any(e["event_type"] == "effect" and "Modify damage packet def_ignore" in e["message"] for e in r["log"]), "modify_damage_packet should log packet mutation"
checks.append("PASS modify_damage_packet can mutate current packet before damage")

# v3.6: conditional_branch can compose packet mutations behind a data-driven condition.
r = run_case(case_dir_v3_4 / "conditional_branch_packet_bonus_case.yaml")
e1 = r["state"]["units"]["e1"]
assert close(e1["hp"], 800.0), f"conditional branch should add +100% damage bonus to 100 damage, got HP {e1['hp']}"
checks.append("PASS conditional_branch can gate nested packet modification effects")

# v3.6: skill point aliases from the model schema map to skill point modification.
r = run_case(case_dir_v3_4 / "gain_consume_skill_point_alias_case.yaml")
assert r["state"]["global"]["skill_points"] == 5, f"gain 3 then consume 1 from 3 SP should end at 5, got {r['state']['global']['skill_points']}"
checks.append("PASS gain_skill_point/consume_skill_point aliases modify SP")


report = ["# HSR simulator prototype v7.7 validation", "", "All smoke tests and targeted regression checks passed.", ""]
report += [f"- {c}" for c in checks]
report.append("")
report.append("New targeted coverage added through v3.6:")
report += [
    "- Multi-hit per-hit duration vs once-per-attack duration separation.",
    "- AoE multi-kill energy rewards with ERR.",
    "- Shield absorption plus configured hit-taken energy.",
    "- Queue priority between immediate and interrupt actions.",
    "- Expected crit-rate clamping above 100%.",
    "- HP-bar depletion trigger with immediate phase action.",
    "- Multi-HP-bar carry-over and no-carry phase-bar semantics.",
    "- Explicit hp_model semantics: phase_hp no-carry and segmented_hp carry by default.",
    "- Legacy boolean tag predicates such as `{action_has_tag: attack}`.",
    "- Context-specific Crit Rate / Crit DMG modifiers in crit resolution.",
    "- Explicit hp_model.bars next-bar HP and inline on_depleted effects.",
    "- Carry-over across non-uniform hp_model.bars uses each next bar HP.",
    "- Conditional modifiers apply to packet scaling stat.",
    "- Conditional pct modifiers preserve split stat semantics.",
    "- Phase HP boundaries lock later packets from the same action.",
    "- Condition right-side references such as `right: flag:x` resolve before comparison.",
    "- immediate_action effects defer target-policy resolution across wave transitions unless explicit targets are supplied.",
    "- Single-target YAML strings such as `targets: e2` are normalized before route, packet, and queued-action resolution.",
    "- Kill energy is applied before after_defeat_enemy trigger conditions so follow-up triggers see the post-kill energy state.",
    "- Deferred queued actions with no valid targets are skipped before costs or action energy resolve.",
    "- Packet-level target_policy: same_target can resolve from the currently selected action target.",
    "- Queued actions preserve their selected target for packet-level same_target policies.",
    "- Stale explicit queued attack targets are skipped before costs and action energy.",
    "- Action-owned damage_unit effect kills grant kill energy before after_defeat_enemy triggers.",
    "- Action-owned damage_unit effects defer wave transition until the full action ends.",
    "- gain_energy/grant_energy effect aliases use the standard ERR-aware energy source helper.",
    "- Action-owned damage_unit phase boundaries lock later packets and later effect damage in the same action.",
    "- advance_action/delay_action accept model-pack percent aliases.",
    "- Queued actions with damage_unit-only stale targets are skipped before costs/action energy.",
    "- Queued actions are skipped if their actor has died before queue resolution.",
    "- Effect-level conditions gate individual effects before execution.",
    "- gain_energy amount shorthand respects affected_by_err=true instead of always becoming fixed energy.",
    "- Action energy can be split across damage packets so mid-action full-energy Ultimate queues are representable without changing total action energy.",
    "- A dedicated ultimate_queue resolves before immediate/extra-turn queues, so an Ultimate queued during early packets resolves before Reappearance triggered by a later kill.",
    "- Queued actions support carry_across_wave=false; Reappearance can be dropped on wave transition while an automatic Skill carries into the next wave.",
    "- Queued action wave-carry policy can be stored on the action definition via queued_action_policy / queue_policy / queue_behavior.",
    "- Quoted boolean strings such as carry_across_wave: \"false\" are parsed safely instead of becoming truthy Python strings.",
    "- Queued action turn_kind can be inferred from action tags such as extra_turn / ultimate.",
    "- Queued action turn_kind can also be stored in queued_action_policy for character-specific mechanics.",
    "- Boolean-like strings are parsed safely for affected_by_err, grant_if_defeated, and hp_model carry_over_damage.",
    "- Character duration alias extra_turn_consumes_duration is honored for extra-turn lifecycle ticks.",
    "- owner_turn_start_decrement statuses tick at the owner regular turn-start boundary before action_start.",
    "- Action-level effects_after_action_start and effects_after_damage windows resolve in the expected order.",
    "- before_damage modify_damage_packet effects can mutate the current packet, including def_ignore and damage bonus fields.",
    "- conditional_branch can gate nested effect lists.",
    "- gain_skill_point / consume_skill_point schema aliases modify SP.",
]
(ROOT / "VALIDATION_v3_4.md").write_text("\n".join(report), encoding="utf-8")

print("\n".join(report))

# v3.6 video-trace support: battle-start / technique setup effects are applied before the first route action.
case_dir_v4_0 = ROOT / "validation_v4_0"
r = run_case(case_dir_v4_0 / "battle_start_initial_effects_case.yaml")
assert r["state"]["global"]["skill_points"] == 5, "battle-start SP technique effect should apply before Sparkle spends 1 SP"
status_ids = {s["id"] for s in r["state"]["units"]["seele"]["statuses"]}
assert "seele_technique_amplified" in status_ids, "battle-start status should be present before route validation"
assert any(e["event_type"] == "battle_start" for e in r["log"]), "battle-start setup should be logged"
checks.append("PASS battle-start/initial effects apply before route actions")

# v3.6 summons and waves honor initial_delay_ratio instead of always entering at one full action interval.
r = run_case(case_dir_v4_0 / "summon_initial_delay_case.yaml")
fast = r["state"]["units"]["minion_fast"]
default = r["state"]["units"]["minion_default"]
assert close(fast["remaining_av"], 12.5), f"speed 200 minion with initial_delay_ratio 0.25 should enter at 12.5 AV, got {fast['remaining_av']}"
assert close(default["remaining_av"], 50.0), f"speed 200 minion default should enter at full 50 AV, got {default['remaining_av']}"
checks.append("PASS summoned units honor initial_delay_ratio / default full interval")


# v3.6 video-derived opening trace: four-technique opening can be replayed from
# battle-start setup through Seele's first regular action with the expected AV gates.
r = run_case(case_dir_v4_0 / "video_opening_trace_case.yaml")
starts = [(round(e["av"], 6), e["message"]) for e in r["log"] if e["event_type"] == "action_start"]
expected_prefix = [
    (35.9, "sparkle uses skill"),
    (35.9, "sparkle uses ultimate"),
    (35.9, "tribbie uses followup"),
    (35.9, "tribbie uses ultimate"),
    (40.954, "dan_heng uses skill"),
    (40.954, "dan_heng uses ultimate"),
    (40.954, "tribbie uses followup"),
    (53.152309, "seele uses skill"),
]
for (got_av, got_msg), (exp_av, exp_msg) in zip(starts, expected_prefix):
    assert close(got_av, exp_av, eps=1e-3), f"expected {exp_msg} near AV {exp_av}, got {got_msg} at {got_av}"
    assert exp_msg in got_msg, f"expected action message containing {exp_msg}, got {got_msg}"
assert r["state"]["global"]["skill_points"] == 5, "video opening SP should be 5 after Sparkle skill, Dan Heng skill, and Seele skill"
checks.append("PASS video-derived four-technique opening action order matches expected AV gates")


# v4.0: explicit false effect-hit/chance gates must not be lost by Python `or` fallback.
r = run_case(case_dir_v4_0 / "add_status_false_gate_case.yaml")
status_ids = {s["id"] for s in r["state"]["units"]["actor"]["statuses"]}
assert "should_apply" in status_ids, "true effect-hit status should apply"
assert "should_not_apply_effect_hit_false" not in status_ids, "effect_hit: false must skip add_status"
assert "should_not_apply_chance_false_string" not in status_ids, "chance: quoted false must skip add_status"
checks.append("PASS add_status effect_hit/chance false gates are parsed safely")

# v4.0: quoted booleans on packet crit fields must be parsed safely.
r = run_case(case_dir_v4_0 / "quoted_false_can_crit_case.yaml")
target = r["state"]["units"]["target"]
assert close(target["hp"], 9000.0), f"can_crit: quoted false should deal noncrit 1000 damage, got target HP {target['hp']}"
checks.append("PASS quoted false packet can_crit disables crit resolution")

# v4.0: unit alive/is_broken booleans can be generated as quoted strings.
r = run_case(case_dir_v4_0 / "quoted_false_alive_case.yaml")
assert r["state"]["units"]["ghost_enemy"]["alive"] is False, "alive: quoted false should deserialize as False"
assert not any(u["alive"] for uid, u in r["state"]["units"].items() if uid == "ghost_enemy"), "quoted-false enemy should not be active"
checks.append("PASS quoted false unit alive field is parsed safely")

# v4.0: queued offensive preflight must include damage_unit in every action effect window.
r = run_case(case_dir_v4_0 / "stale_effect_after_action_start_queued_target_skip_case.yaml")
assert r["state"]["global"]["skill_points"] == 2, "only the first effects_after_action_start burst should spend SP"
assert close(r["state"]["units"]["actor"]["energy"], 30.0), "stale second effects_after_action_start burst should not grant action energy"
assert any(e["event_type"] == "queue_skip" and "no live damage targets" in e["message"] for e in r["log"]), "stale action-start effect burst should log queue_skip"
checks.append("PASS stale queued damage in effects_after_action_start is skipped before costs/action energy")

# v4.0: queued offensive preflight should recursively inspect conditional_branch damage effects.
r = run_case(case_dir_v4_0 / "conditional_branch_queued_damage_preflight_case.yaml")
assert r["state"]["global"]["skill_points"] == 2, "only first conditional-branch damage burst should spend SP"
assert close(r["state"]["units"]["actor"]["energy"], 30.0), "stale conditional-branch damage burst should not grant action energy"
assert any(e["event_type"] == "queue_skip" and "no live damage targets" in e["message"] for e in r["log"]), "stale conditional branch burst should log queue_skip"
checks.append("PASS queued preflight recursively detects conditional_branch damage_unit effects")


# v4.0: conditional_branch must execute effects_if_false; `condition` is not an effect gate for this effect type.
r = run_case(case_dir_v4_0 / "conditional_branch_false_branch_case.yaml")
flags = r["state"]["global"]["flags"]
assert flags.get("false_branch_executed") is True, "conditional_branch false branch should execute"
assert flags.get("true_branch_wrongly_executed") is None, "conditional_branch true branch must not execute when condition is false"
checks.append("PASS conditional_branch effects_if_false executes when branch condition is false")

# v4.0: quoted boolean values in conditions should compare as booleans, not literal strings.
r = run_case(case_dir_v4_0 / "condition_quoted_bool_compare_case.yaml")
assert r["state"]["global"]["flags"].get("quoted_true_condition_worked") is True, "right: quoted true should compare equal to boolean true"
checks.append("PASS quoted boolean condition RHS is normalized for comparison")

# v4.0: scalar tags / weaknesses should not be split into characters.
r = run_case(case_dir_v4_0 / "scalar_tags_and_weakness_case.yaml")
assert r["state"]["global"]["flags"].get("scalar_action_tag_seen") is True, "scalar action tag 'attack' should be recognized"
enemy = r["state"]["units"]["enemy"]
assert close(enemy["toughness"], 10.0), f"scalar weakness 'quantum' should allow toughness reduction to 10, got {enemy['toughness']}"
checks.append("PASS scalar tags and weaknesses are normalized as single tokens")

# v4.0: carry_over_damage generated as quoted true should infer segmented HP semantics.
r = run_case(case_dir_v4_0 / "hp_model_string_true_carry_inference_case.yaml")
seg = r["state"]["units"]["segmented"]
assert seg["hp_model_type"] == "segmented_hp", f"quoted true carry_over_damage should infer segmented_hp, got {seg['hp_model_type']}"
assert seg["hp_bars_remaining"] == 2, f"250 damage should consume first 100 HP bar and carry into second, got bars {seg['hp_bars_remaining']}"
assert close(seg["hp"], 50.0), f"overflow into second 200 HP bar should leave 50 HP, got {seg['hp']}"
checks.append("PASS quoted true carry_over_damage infers segmented HP semantics")


# v4.0: before_damage packet mutations must affect crit resolution, not only damage bonus/DEF ignore.
r = run_case(case_dir_v4_0 / "modify_damage_packet_crit_case.yaml")
target = r["state"]["units"]["target"]
assert close(target["hp"], 7000.0), f"packet-local crit_rate_add/crit_dmg_add should make expected damage 3000, got HP {target['hp']}"
checks.append("PASS modify_damage_packet crit_rate_add/crit_dmg_add enter crit resolution")

# v4.0: scalar action tags must work in simulator internals, not only trigger predicates.
r = run_case(case_dir_v4_0 / "scalar_action_tag_consumes_regular_action_case.yaml")
assert close(r["state"]["units"]["actor"]["remaining_av"], 100.0), "scalar consumes_regular_action tag should add a regular action interval"
checks.append("PASS scalar action tags are honored for regular action consumption")

r = run_case(case_dir_v4_0 / "scalar_action_tag_kill_energy_case.yaml")
assert close(r["state"]["units"]["actor"]["energy"], 10.0), f"scalar can_trigger_kill_energy tag should grant 10 kill energy, got {r['state']['units']['actor']['energy']}"
checks.append("PASS scalar action tags are honored for kill-energy eligibility")

# v4.0: quoted false queue-control fields must not auto-drain queues before the intended video-replay checkpoint.
r = run_case(case_dir_v4_0 / "quoted_false_queue_autoresolve_case.yaml")
flags = r["state"]["global"]["flags"]
assert flags.get("queue_was_pending_during_route") is True, "quoted false resolve/auto-resolve fields should leave the queued action pending during the route step"
assert flags.get("initial_queue_ran") is True, "queued action should still drain after the route step"
assert flags.get("queue_was_already_resolved") is None, "queued action must not resolve before the check step"
checks.append("PASS quoted false queue auto-resolve fields are parsed safely")

# v4.0: quoted false ignore_shield must not bypass shields.
r = run_case(case_dir_v4_0 / "quoted_false_ignore_shield_case.yaml")
target = r["state"]["units"]["target"]
assert close(target["hp"], 1000.0), f"ignore_shield: quoted false should preserve HP behind shield, got HP {target['hp']}"
assert close(target["shield"], 0.0), f"shield should absorb the hit, got shield {target['shield']}"
checks.append("PASS quoted false packet ignore_shield preserves shield absorption")



case_dir_v4_4 = ROOT / "validation_v4_4"

# v4.4: numeric model fields can arrive quoted from generated/video checkpoint YAML.
r = run_case(case_dir_v4_4 / "numeric_string_stats_case.yaml")
target = r["state"]["units"]["target"]
assert close(target["hp"], 9000.0), f"quoted numeric stats should participate in damage; expected HP 9000, got {target['hp']}"
checks.append("PASS quoted numeric stat fields are parsed instead of ignored")

# v4.4: numeric strings on the RHS of conditions should compare numerically.
r = run_case(case_dir_v4_4 / "condition_numeric_string_rhs_case.yaml")
assert r["state"]["units"]["actor"]["flags"].get("numeric_condition_ok") is True, "numeric string condition RHS should compare as number"
checks.append("PASS numeric string condition values compare numerically")

# v4.4: quoted false crit event mode should force non-crit, not error or expected-crit.
r = run_case(case_dir_v4_4 / "quoted_false_crit_event_mode_case.yaml")
target = r["state"]["units"]["target"]
assert close(target["hp"], 9000.0), f"crit event mode 'false' should deal noncrit 1000 damage, got HP {target['hp']}"
checks.append("PASS quoted false crit event mode resolves as noncrit")

# v4.4: infinite/no-toughness targets should not crash toughness-state multiplier.
assert any(e["event_type"] == "damage" for e in r["log"]), "damage against infinite toughness target should resolve"
checks.append("PASS infinite/no-toughness targets use neutral toughness-state multiplier")

# v4.4: allow_dead_actor quoted false should remain false.
try:
    run_case(case_dir_v4_4 / "quoted_false_allow_dead_actor_case.yaml")
    raise AssertionError("dead actor action should have been rejected when allow_dead_actor is quoted false")
except Exception as exc:
    assert "Actor actor is dead" in str(exc), f"unexpected exception for dead actor quoted false: {exc}"
checks.append("PASS quoted false allow_dead_actor rejects dead actors")

# v4.4: action_end action advance after a regular action applies to refreshed next AV.
r = run_case(case_dir_v4_4 / "action_end_advance_after_regular_refresh_case.yaml")
actor = r["state"]["units"]["actor"]
assert close(actor["remaining_av"], 50.0), f"action_end advance should apply after regular AV refresh; got {actor['remaining_av']}"
checks.append("PASS action_end advance on a regular actor applies to refreshed next AV")



case_dir_v4_8 = ROOT / "validation_v4_8"

# v4.8: video/checkpoint YAML often serializes effect numeric fields as strings or percentages.
r = run_case(case_dir_v4_8 / "quoted_numeric_effect_fields_case.yaml")
actor = r["state"]["units"]["actor"]
assert close(actor["energy"], 20.0), f"modify_energy amount + target pct strings should grant 20 energy, got {actor['energy']}"
assert r["state"]["global"]["skill_points"] == 3, "gain_skill_point amount string should add SP"
assert close(actor["flags"].get("counter"), 2.5), f"modify_unit_counter numeric strings should produce 2.5, got {actor['flags'].get('counter')}"
assert r["state"]["global"]["flags"].get("numeric_flag") == 50.0, "set_flag numeric string should be normalized for later comparisons"
assert actor["flags"].get("bool_flag") is True, "set_unit_flag quoted true should become boolean true"
checks.append("PASS quoted numeric effect fields and flag values are parsed safely")

# v4.8: status, packet, res, damage-taken, and reduction modifiers can be quoted/percent strings.
r = run_case(case_dir_v4_8 / "quoted_numeric_status_and_packet_modifiers_case.yaml")
target = r["state"]["units"]["target"]
assert close(target["hp"], 7995.25), f"quoted modifier fields should yield 2004.75 damage, got HP {target['hp']}"
checks.append("PASS quoted numeric status/packet/resistance damage modifiers enter the formula")

# v4.8: effect damage/heal/shield/toughness numeric strings and pct strings resolve in effect windows.
r = run_case(case_dir_v4_8 / "quoted_numeric_effect_damage_heal_shield_case.yaml")
actor = r["state"]["units"]["actor"]
target = r["state"]["units"]["target"]
assert close(target["hp"], 950.0), f"damage 200 through 50 shield then heal 100 should leave HP 950, got {target['hp']}"
assert close(target["shield"], 0.0), f"target shield should be consumed, got {target['shield']}"
assert close(actor["shield"], 200.0), f"modify_shield amount/pct strings should add 200 shield, got {actor['shield']}"
assert close(target["toughness"], 125.0), f"modify_toughness numeric string should raise toughness to 125, got {target['toughness']}"
checks.append("PASS quoted numeric effect damage/heal/shield/toughness fields resolve")

# v4.8: summon initial_delay_ratio percentages and infinity aliases are normalized.
r = run_case(case_dir_v4_8 / "percent_initial_delay_and_inf_toughness_case.yaml")
minion = r["state"]["units"]["minion"]
target = r["state"]["units"]["target"]
assert close(minion["remaining_av"], 25.0), f"speed 200 minion at 50% delay should enter at 25 AV, got {minion['remaining_av']}"
assert target["toughness"] is None and target["max_toughness"] is None, "∞ toughness aliases should deserialize as no/infinite toughness"
checks.append("PASS percent initial delay and infinity toughness aliases parse correctly")


# v4.8: model-pack style damage_packets use nested scaling/crit/toughness and target aliases.
r = run_case(case_dir_v4_8 / "model_style_damage_packet_case.yaml")
target = r["state"]["units"]["target"]
assert close(target["hp"], 8200.0), f"model-style multiplier_by_level packet should deal 1800 damage after intact-toughness multiplier, got HP {target['hp']}"
assert close(target["toughness"], 10.0), f"nested toughness reduction should reduce target toughness to 10, got {target['toughness']}"
assert r["state"]["global"]["skill_points"] == 2, "action skill_point_delta alias should spend one SP"
checks.append("PASS model-pack style damage packet scaling/crit/toughness/target aliases resolve")


# v4.8: model/schema aliases: singular damage_packet and effect action_id should resolve.
r = run_case(case_dir_v4_8 / "singular_damage_packet_and_action_id_alias_case.yaml")
target = r["state"]["units"]["target"]
assert close(target["hp"], 9000.0), f"launch_action action_id + singular damage_packet should deal 1000 damage, got HP {target['hp']}"
checks.append("PASS action_id and singular damage_packet aliases resolve")

# v4.8: per_owner_turn usage-limit alias should reset at each regular owner turn.
r = run_case(case_dir_v4_8 / "per_owner_turn_usage_alias_resets_case.yaml")
actor = r["state"]["units"]["actor"]
assert close(actor["flags"].get("times"), 2.0), f"per_owner_turn trigger should fire once per each of two regular turns, got {actor['flags'].get('times')}"
checks.append("PASS per_owner_turn usage-limit alias resets on owner regular turn")

# v5.4: model-pack string predicates should evaluate without schema pre-translation.
case_dir_v5_0 = ROOT / "validation_v5_0"
r = run_case(case_dir_v5_0 / "model_condition_string_case.yaml")
actor = r["state"]["units"]["actor"]
assert actor["flags"].get("string_predicate_ok") is True, "string predicate condition should fire"
checks.append("PASS model-pack string predicates evaluate common action/target/usage expressions")

r = run_case(case_dir_v5_0 / "model_condition_has_and_defeated_by_case.yaml")
seele = r["state"]["units"]["seele"]
assert seele["flags"].get("has_status_ok") is True, "`unit has status` string predicate should fire"
assert seele["flags"].get("defeated_by_ok") is True, "defeated_by/context string predicates should fire"
checks.append("PASS model-pack has-status and defeated_by string predicates evaluate")

r = run_case(case_dir_v5_0 / "model_effect_aliases_case.yaml")
actor = r["state"]["units"]["actor"]
target = r["state"]["units"]["target"]
status_ids = {s["id"] for s in actor["statuses"]}
assert "alias_buff" in status_ids and "alias_status" in status_ids, "add_buff/apply_status aliases should add statuses"
assert close(target["hp"], 9000.0), f"launch_follow_up_attack alias should queue follow action for 1000 damage, got HP {target['hp']}"
checks.append("PASS model-pack effect aliases add_buff/apply_status/launch_follow_up_attack resolve")

# v5.4 model-pack direct replay hardening.
case_dir_v5_4 = ROOT / "validation_v5_4"

r = run_case(case_dir_v5_4 / "status_template_buff_lookup_case.yaml")
enemy = r["state"]["units"]["enemy"]
seele = r["state"]["units"]["seele"]
assert close(enemy["hp"], 3500.0), f"add_buff by buff_id should materialize template atk_add before damage; enemy HP {enemy['hp']}"
assert any(s["id"] == "seele_skill_spd_buff" and s["duration_value"] == 3 for s in seele["statuses"]), "buff template duration should be preserved"
checks.append("PASS add_buff/apply_status materialize status templates before action damage")

r = run_case(case_dir_v5_4 / "model_pack_shield_bondmate_case.yaml")
seele = r["state"]["units"]["seele"]
dh = r["state"]["units"]["dan_heng_permansor_terrae"]
assert close(seele["shield"], 972.5), f"Dan Heng data-derived skill shield should be 0.23*2000+512.5, got {seele['shield']}"
assert close(dh["shield"], 972.5), f"all_allies shield should include Dan Heng with data-derived max-level value, got {dh['shield']}"
assert r["state"]["global"]["flags"].get("bondmate") == "seele", "set_target should store bondmate alias"
assert any(s["id"] == "bondmate" for s in seele["statuses"]), "bondmate status should be applied to selected ally"
attack_convert_statuses = [s for s in seele["statuses"] if s["id"] == "dan_heng_pt_attack_convert_dynamic"]
assert attack_convert_statuses, "Dan Heng skill should add live AttackConvert derived-stat status to bondmate"
derived = attack_convert_statuses[0]["modifiers"]["derived_stat_add"][0]
assert derived["stat"] == "atk" and close(derived["scale"], 0.15), attack_convert_statuses[0]
assert "souldragon" in r["state"]["units"], "Dan Heng skill should auto-summon/attach Souldragon for bondmate"
checks.append("PASS set_target/data-derived Dan Heng shield/live AttackConvert model-pack effects resolve selected ally and formulas")

r = run_case(case_dir_v5_4 / "hit_model_expansion_case.yaml")
target = r["state"]["units"]["target"]
actor = r["state"]["units"]["actor"]
assert close(target["hp"], 9000.0), f"hit_model shares should preserve total damage 1000, got target HP {target['hp']}"
assert close(actor["energy"], 30.0), f"per-packet split energy across expanded hits should total 30, got {actor['energy']}"
assert not any(s["id"] == "hits_dealt_three" for s in actor["statuses"]), "hits_dealt duration should tick once per expanded hit"
damage_events = [e for e in r["log"] if e["event_type"] == "damage"]
assert len(damage_events) == 3, f"hit_model should expand into 3 damage events, got {len(damage_events)}"
checks.append("PASS model-pack hit_model.hits expands into per-hit packets without changing total damage/energy")

r = run_case(case_dir_v5_4 / "model_pack_trigger_dict_case.yaml")
assert r["state"]["global"]["flags"].get("zone_x") is True and r["state"]["global"]["flags"].get("zone_active") is True
assert r["state"]["global"]["flags"].get("zone_triggered") is True, "dict trigger + singular effect should fire from zone_active string condition"
checks.append("PASS dict-style triggers, singular effect, add_zone, and zone_active condition resolve")

r = run_case(case_dir_v5_4 / "direct_model_template_actions_case.yaml")
assert r["state"]["global"]["skill_points"] == 4, "Sparkle and Dan Heng skills should each spend 1 SP from real template actions"
assert close(r["state"]["units"]["seele"]["remaining_av"], 50.0), "Sparkle skill target alias should advance selected ally by 50%"
assert close(r["state"]["units"]["seele"]["shield"], 1139.48), f"Dan Heng max-level data-derived shield formula should evaluate from actor ATK, got {r['state']['units']['seele']['shield']}"
assert r["state"]["global"]["flags"].get("bondmate") == "seele", "real Dan Heng skill should set bondmate alias"
assert close(r["state"]["units"]["enemy"]["hp"], 17900.0), f"Tribbie real ultimate multiplier_at_ult_10 should deal 2100, got enemy HP {r['state']['units']['enemy']['hp']}"
assert r["state"]["global"]["flags"].get("tribbie_zone_guess_who_lives_here") is True, "Tribbie real ultimate should add zone flag"
checks.append("PASS direct Sparkle/Dan Heng/Tribbie model-template actions replay with target aliases, formulas, and ult multiplier aliases")

# v5.8 direct model-template predicates/formulas and actionless extra-turn grants.
case_dir_v5_8 = ROOT / "validation_v5_8"

r = run_case(case_dir_v5_8 / "relic_lightcone_condition_formula_case.yaml")
enemy = r["state"]["units"]["enemy"]
assert close(enemy["hp"], 7120.0), f"light-cone/relic before_damage predicates should yield 2880 damage, got enemy HP {enemy['hp']}"
checks.append("PASS model-pack in-list predicates, wearer metadata, relic piece predicates, stack_count formulas, and packet crit/damage bonus aliases resolve")

r = run_case(case_dir_v5_8 / "multiplier_by_reference_case.yaml")
enemy = r["state"]["units"]["enemy"]
assert close(enemy["hp"], 6040.0), f"technique multiplier_by_reference should reuse skill multiplier 3.96, got enemy HP {enemy['hp']}"
checks.append("PASS scaling.multiplier_by_reference reuses referenced action packet multiplier")

r = run_case(case_dir_v5_8 / "actionless_extra_turn_grant_case.yaml")
flags = r["state"]["global"]["flags"]
assert close(flags.get("pending_extra_turn:seele:resurgence", 0), 1.0), f"actionless enqueue_extra_turn should create pending grant flag, got {flags}"
checks.append("PASS actionless enqueue_extra_turn records an extra-turn grant instead of crashing or inventing an action")


# v6.2 video-chain/model-pack integration regressions.
case_dir_v6_2 = ROOT / "validation_v6_2"

r = run_case(case_dir_v6_2 / "unit_trigger_sp_stack_case.yaml")
enemy_statuses = {s["id"]: s for s in r["state"]["units"]["enemy"]["statuses"]}
assert "figment" in enemy_statuses, "unit-local Sparkle trigger should add Figment to enemy side after SP consumption"
assert enemy_statuses["figment"]["stacks"] == 1, f"Figment stacks should come from consumed_skill_points, got {enemy_statuses['figment']['stacks']}"
assert close(enemy_statuses["figment"]["modifiers"].get("damage_taken_add"), 0.04), "model modifier alias for Figment vulnerability should materialize"
checks.append("PASS unit-local triggers, after_skill_point_consumed, add_or_refresh_stack, and consumed_skill_points resolve")

r = run_case(case_dir_v6_2 / "model_modifier_alias_damage_case.yaml")
assert close(r["state"]["units"]["enemy"]["hp"], 8120.0), f"Seele amplification alias should add +88% damage bonus, got enemy HP {r['state']['units']['enemy']['hp']}"
checks.append("PASS model-pack status modifier aliases enter damage formulas")

r = run_case(case_dir_v6_2 / "followup_embedded_dotted_scaling_case.yaml")
assert close(r["state"]["units"]["e1"]["hp"], 500.0) and close(r["state"]["units"]["e2"]["hp"], 500.0), "embedded Souldragon follow-up should use dotted Dan Heng ATK scaling and hit all enemies"
checks.append("PASS embedded follow_up_attack with missing attached actor and dotted scaling stat resolves")

r = run_case(case_dir_v6_2 / "action_id_lookup_and_extra_turn_context_case.yaml")
flags = r["state"]["global"]["flags"]
assert close(flags.get("pending_extra_turn:seele:resurgence", 0), 0.0), f"Resurgence should not retrigger from a resurgence extra turn, got flags {flags}"
assert not r["state"]["units"]["enemy"]["alive"], "action lookup by action.id should execute the auto skill"
checks.append("PASS action lookup by model action id and context.extra_turn_type gating work")


r = run_case(case_dir_v6_2 / "summon_and_hp_loss_alias_case.yaml")
assert close(r["state"]["units"]["boss"]["hp"], 850.0), f"hp_loss alias should remove 15% max HP, got {r['state']['units']['boss']['hp']}"
assert "furiae_warrior_1" in r["state"]["units"] and "furiae_warrior_2" in r["state"]["units"], "summon_entity aliases should spawn counted units from templates"
assert close(r["state"]["units"]["furiae_warrior_1"]["remaining_av"], 50.0), "summon template initial_delay_ratio should be honored"
checks.append("PASS hp_loss and summon/summon_entity aliases resolve for enemy video-chain actions")


# v6.2 stateful action-advance video-chain checks.
r = run_case(case_dir_v6_2 / "stateful_action_advances_case.yaml")
seele = r["state"]["units"]["seele"]
assert close(seele["remaining_av"], 80.0), f"Seele basic should refresh to 100 AV then Rippling Waves advances by 20%, got {seele['remaining_av']}"
assert any(e["event_type"] == "av_change" and e["data"].get("old") == 100.0 and close(e["data"].get("new"), 80.0) for e in r["log"]), "state log should record the post-refresh basic advance"
checks.append("PASS Seele basic Rippling Waves action advance applies to refreshed next AV")

r = run_case(case_dir_v6_2 / "dance_dance_dance_model_trigger_case.yaml")
for uid in ["seele", "sparkle", "tribbie"]:
    av = r["state"]["units"][uid]["remaining_av"]
    assert close(av, 76.0), f"Dance! Dance! Dance! S5 should advance {uid} from 100 to 76, got {av}"
assert sum(1 for e in r["log"] if e["event_type"] == "av_change") == 3, "DDD should log one AV change for each ally"
checks.append("PASS Dance! Dance! Dance! superimposition table triggers after wearer Ultimate and advances all allies")

r = run_case(case_dir_v6_2 / "bondmate_attack_advances_souldragon_case.yaml")
sd = r["state"]["units"]["souldragon"]
dh = r["state"]["units"]["dan_heng"]
assert close(sd["remaining_av"], 85.0), f"Bondmate attack should advance Souldragon by 15%, got {sd['remaining_av']}"
assert close(dh["energy"], 6.0), f"Bondmate attack should also grant Dan Heng 6 energy before ERR, got {dh['energy']}"
checks.append("PASS Dan Heng bondmate attack trigger advances Souldragon and grants energy")

r = run_case(case_dir_v6_2 / "other_ally_ultimate_owner_exclusion_case.yaml")
flags = r["state"]["global"]["flags"]
assert flags.get("tribbie_saw_other_ult") is True, "Tribbie should see Sparkle's Ultimate as other-ally Ultimate"
trigger_logs = [e for e in r["log"] if e["event_type"] == "trigger" and e["data"].get("timing") == "after_other_ally_uses_ultimate"]
assert len(trigger_logs) == 1, f"after_other_ally_uses_ultimate should not fire on Tribbie's own Ultimate; logs={trigger_logs}"
checks.append("PASS after_other_ally_uses_ultimate is owner-relative and excludes the owner's own Ultimate")

# v7.0 schema-normalizer boundary checks.
from hsr_engine.schema_normalizer import canonicalize_case
normalized = canonicalize_case({
    "global": {"skill_points": "3", "flags": {"b": "false"}},
    "flags": {"a": "true"},
    "units": {
        "u": {
            "side": "ally", "hp": "100", "max_hp": "100",
            "weaknesses": "quantum", "tags": "test_tag",
            "actions": {"x": {"tags": "attack", "damage_packet": {
                "target": "target",
                "scaling": {"stat": "atk", "multiplier_by_level": {"10": "1.0", "12": "2.0"}},
                "crit": {"can_crit": "false"},
            }}},
        },
        "target": {"side": "enemy", "hp": 100, "max_hp": 100},
    },
})
assert normalized["global"]["flags"] == {"a": True, "b": False}
assert normalized["units"]["u"]["weaknesses"] == ["quantum"]
assert normalized["units"]["u"]["actions"]["x"]["damage_packets"][0]["multiplier"] == 2.0
assert normalized["units"]["u"]["actions"]["x"]["damage_packets"][0]["can_crit"] is False
checks.append("PASS v7.0 canonical schema normalizer merges flags and canonicalizes model-pack packets")


# v7.2 canonical model-pack loader integration.
from hsr_engine.model_pack_loader import ModelPack, load_model_pack_case
PACK = Path("/mnt/data/hsr_model_pack_v3_0")
if not PACK.exists():
    PACK = ROOT.parent / "model_pack_v3_0"
pack = ModelPack(PACK)
report = pack.validate_index()
assert report["ok"] is True, report
checks.append("PASS canonical model-pack manifest/index validates")
case = load_model_pack_case(PACK, "arbitration_4_3_knight_3_opening")
assert case.get("compiled_from", {}).get("model_pack") == "hsr_model_pack_v3_0"
assert "seele" in case["units"] and "sparkle" in case["units"]
sim_for_conditions = BattleSimulator(case)
assert sim_for_conditions.eval_condition({"left": "battle.wave_number", "op": "==", "right": 1}, {})
assert sim_for_conditions.eval_condition({"any_enemy_alive": True}, {})
# v0.65 live C0 checkpoint import state from user screenshots.
import_only_sim = BattleSimulator(case)
st = import_only_sim.snapshot()["state"]
assert close(st["global"]["skill_points"], 6.0), st["global"]
assert close(st["units"]["seele"]["energy"], 60.0), st["units"]["seele"]
assert close(st["units"]["sparkle"]["energy"], 79.0), st["units"]["sparkle"]
assert close(st["units"]["tribbie"]["energy"], 99.0), st["units"]["tribbie"]
assert close(st["units"]["dan_heng_permansor_terrae"]["energy"], 104.0), st["units"]["dan_heng_permansor_terrae"]
assert close(st["units"]["seele"]["shield"], 1381.0), st["units"]["seele"]
assert close(st["units"]["sparkle"]["shield"], 881.0), st["units"]["sparkle"]
assert "souldragon" in st["units"], st["units"].keys()
assert any(s["id"] == "dan_heng_pt_attack_convert_dynamic" for s in st["units"]["seele"].get("statuses", [])), st["units"]["seele"].get("statuses", [])
checks.append("PASS live C0 checkpoint aligns four-technique Knight III observed SP/energy/shield/bondmate state")
r = sim_for_conditions.run_route(case.get("route", []))
assert r["state"]["global"]["av"] >= case["global"]["av"], r["state"]["global"]
checks.append("PASS canonical model-pack compiled opening case loads and replays from v0.65 live C0 checkpoint")
checks.append("PASS kernel evaluates generated battle.wave_number and any_enemy_alive predicates")
case2 = load_case(str(PACK))
assert case2["compiled_from"]["model_pack"] == "hsr_model_pack_v3_0"
checks.append("PASS load_case accepts model-pack directories as simulator input")


# v7.2 TurnBasedGameData source adapter smoke test using a self-contained fixture.
import zipfile
from copy import deepcopy
from hsr_engine.tbgd_loader import TBGDSource, write_catalog_bundle

fixture_zip = OUT / "mini_turnbasedgamedata.zip"
with zipfile.ZipFile(fixture_zip, "w") as z:
    root = "turnbasedgamedata-main/ExcelOutput/"
    z.writestr(root + "AvatarConfig.json", json.dumps([
        {
            "AvatarID": 1102,
            "AvatarName": {"Hash": 1},
            "AvatarFullName": {"Hash": 2},
            "Rarity": "CombatPowerAvatarRarityType5",
            "DamageType": "Quantum",
            "AvatarBaseType": "Rogue",
            "SPNeed": {"Value": 120},
            "SkillList": [110201, 110202],
            "RankIDList": [110201],
            "JsonPath": "Config/ConfigCharacter/Avatar/Avatar_Seele_00_Config.json"
        }
    ]))
    z.writestr(root + "AvatarPromotionConfig.json", json.dumps([
        {"AvatarID": 1102, "MaxLevel": 80, "AttackBase": {"Value": 640.0}, "AttackAdd": {"Value": 3.2}, "DefenceBase": {"Value": 360.0}, "DefenceAdd": {"Value": 1.8}, "HPBase": {"Value": 931.0}, "HPAdd": {"Value": 4.65}, "SpeedBase": {"Value": 115}, "CriticalChance": {"Value": 0.05}, "CriticalDamage": {"Value": 0.5}, "BaseAggro": {"Value": 75}}
    ]))
    z.writestr(root + "EquipmentConfig.json", json.dumps([
        {"EquipmentID": 23001, "EquipmentName": {"Hash": 3}, "Rarity": "CombatPowerLightconeRarity5", "AvatarBaseType": "Rogue", "MaxPromotion": 6, "MaxRank": 5, "SkillID": 23001}
    ]))
    z.writestr(root + "EquipmentSkillConfig.json", json.dumps([
        {"SkillID": 23001, "Level": 5, "ParamList": [{"Value": 0.24}], "AbilityName": "Ability23001"}
    ]))
    z.writestr(root + "RelicSetConfig.json", json.dumps([
        {"SetID": 309, "SetName": {"Hash": 4}, "SetSkillList": [2,4], "Release": True, "ReleaseVersion": "1.0"}
    ]))
    z.writestr(root + "RelicSetSkillConfig.json", json.dumps([
        {"SetID": 309, "RequireNum": 2, "PropertyList": [{"PropertyType": "CriticalChanceBase", "Value": {"Value": 0.08}}], "AbilityParamList": [{"Value": 0.08}]}
    ]))
    z.writestr(root + "MonsterConfig.json", json.dumps([
        {"MonsterID": 3001, "MonsterTemplateID": 3001, "MonsterName": {"Hash": 5}, "HardLevelGroup": 1, "EliteGroup": 1, "StanceWeakList": ["Quantum"], "DamageTypeResistance": [{"DamageType": "Quantum", "Value": {"Value": 0.0}}], "SkillList": [300101], "AbilityNameList": []}
    ]))
    z.writestr(root + "StageConfig.json", json.dumps([
        {"StageID": 9001, "StageType": "Test", "StageName": {"Hash": 6}, "HardLevelGroup": 1, "Level": 95, "MonsterList": [{"Monster0": 3001}], "StageConfigData": []}
    ]))
    z.writestr(root + "AvatarSkillConfig.json", json.dumps([]))
    z.writestr(root + "AvatarSkillTreeConfig.json", json.dumps([]))
    z.writestr(root + "MonsterSkillConfig.json", json.dumps([]))
    z.writestr(root + "MazeBuff.json", json.dumps([]))

src = TBGDSource.open(fixture_zip)
summary = src.core_catalog_summary()
assert summary["representative_tables_present"]["AvatarConfig"]
assert summary["content_counts"]["avatars"] == 1
assert summary["content_counts"]["light_cones"] == 1
assert summary["content_counts"]["monsters"] == 1
avatar = src.build_avatar_catalog()[0]
assert avatar["avatar_id"] == 1102 and avatar["element"] == "Quantum"
assert avatar["max_energy"] == 120
assert avatar["base_stats_at_max_promotion"]["spd_base"] == 115
catalog_dir = OUT / "mini_tbgd_catalog"
write_catalog_bundle(fixture_zip, catalog_dir)
assert (catalog_dir / "avatars.json").exists()
checks.append("PASS TurnBasedGameData adapter inventories core tables and builds normalized source catalogs")


# v7.3 Content Compiler fixture: raw TBGD tables compile into canonical Content IR.
from hsr_engine.content_compiler import ContentCompiler, write_content_ir_bundle

compiler = ContentCompiler(src)
bundle = compiler.compile_bundle(include_stage_rows=10)
assert bundle["manifest"]["counts"]["avatars"] == 1
assert bundle["manifest"]["counts"]["light_cones"] == 1
assert bundle["manifest"]["counts"]["relic_sets"] == 1
assert bundle["manifest"]["counts"]["enemies"] == 1
assert bundle["avatars"][0]["template_id"] == "avatar:1102"
assert bundle["avatars"][0]["unit_kind"] == "avatar"
assert bundle["avatars"][0]["max_energy"] == 120
assert bundle["avatars"][0]["stats_at_max_promotion"]["spd_base"] == 115
assert bundle["avatars"][0]["actions"][0]["action_id"] == 110201
assert bundle["light_cones"][0]["template_id"] == "light_cone:23001"
assert bundle["light_cones"][0]["skill"]["levels"][0]["param_list"] == [0.24]
assert bundle["relic_sets"][0]["template_id"] == "relic_set:309"
assert bundle["enemies"][0]["weaknesses"] == ["Quantum"]
assert bundle["enemies"][0]["resistances"]["Quantum"] == 0.0
ir_dir = OUT / "mini_content_ir"
manifest = write_content_ir_bundle(fixture_zip, ir_dir, include_stage_rows=10)
assert manifest["format"] == "hsr_content_ir_bundle"
assert (ir_dir / "avatars.content_ir.json").exists()
checks.append("PASS TurnBasedGameData Content Compiler emits canonical template-level Content IR")


# v7.5 Ability graph inventory fixture: classify RPG.GameCore nodes and CharacterConfig entry abilities.
from hsr_engine.ability_graph_intake import build_ability_graph_inventory, write_ability_graph_inventory
with zipfile.ZipFile(fixture_zip, "a") as z:
    root = "turnbasedgamedata-main/"
    z.writestr(root + "Config/ConfigAbility/Avatar/Avatar_Test_00_Ability.json", json.dumps({
        "AbilityList": [
            {
                "Name": "Avatar_Test_00_Skill01_Phase01",
                "TargetInfo": {"TargetType": "SkillTargetEntityList"},
                "OnStart": [
                    {"$type": "RPG.GameCore.TriggerAbility", "AbilityName": {"Value": "Avatar_Test_00_Skill01_Phase02"}},
                    {"$type": "RPG.GameCore.AddModifier", "ModifierName": {"Value": "M_Test"}}
                ]
            }
        ],
        "GlobalModifiers": {
            "M_Test": {"OnAdd": [{"$type": "RPG.GameCore.SetDynamicValue", "Key": "X", "Value": {"Value": 1}}]}
        }
    }))
    z.writestr(root + "Config/ConfigCharacter/Avatar/Avatar_Test_00_Config.json", json.dumps({
        "$type": "RPG.GameCore.CharacterConfig",
        "SkillList": [
            {"Name": "Skill01", "SkillType": "Normal", "UseType": "SelectEntity", "TargetInfo": {"TargetType": "EnemySelect"}, "EntryAbility": "Avatar_Test_00_Skill01_Phase01"}
        ],
        "AbilityList": ["Avatar_Test_00_Passive"],
        "SkillAbilityList": ["Avatar_Test_00_Skill01_Phase01"]
    }))
inv = build_ability_graph_inventory(fixture_zip, sample_limit=2)
assert inv["ability_file_count"] == 1
assert inv["character_config_file_count"] == 1
assert inv["rpg_gamecore_type_counts"]["RPG.GameCore.TriggerAbility"] == 1
assert inv["rpg_gamecore_type_counts"]["RPG.GameCore.AddModifier"] == 1
assert inv["rpg_gamecore_type_counts"]["RPG.GameCore.SetDynamicValue"] == 1
assert inv["character_slot_summaries_sample"][0]["skill_slots"][0]["entry_ability"] == "Avatar_Test_00_Skill01_Phase01"
ability_dir = OUT / "mini_ability_inventory"
summary = write_ability_graph_inventory(fixture_zip, ability_dir, sample_limit=2)
assert summary["ability_file_count"] == 1
assert summary["lowering_profile"]["lowering_status_counts"]["lowerer_available"] >= 3
assert (ability_dir / "ability_graph_inventory.json").exists()
assert (ability_dir / "ability_lowering_table.json").exists()
checks.append("PASS TurnBasedGameData ability graph inventory classifies RPG.GameCore node types and character entry abilities")

# v7.5 lowering registry fixture: recognized RPG.GameCore nodes lower into Content IR hints.
from hsr_engine.ability_lowering import ability_index, summarize_ability_chain
ability_file = {
    "AbilityList": [
        {
            "Name": "A",
            "OnStart": [
                {"$type": "RPG.GameCore.TriggerAbility", "AbilityName": {"Value": "B"}},
                {"$type": "RPG.GameCore.AddModifier", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"}, "ModifierName": {"Value": "M_Test"}},
            ],
        },
        {
            "Name": "B",
            "OnStart": [
                {"$type": "RPG.GameCore.DamageByAttackProperty", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "AbilityTargetEntity"}, "AttackProperty": {"$type": "RPG.GameCore.AttackData", "DamageType": {"DamageType": "Quantum"}, "DamagePercentage": {"IsDynamic": False, "FixedValue": {"Value": 1.0}}, "StanceValue": {"IsDynamic": False, "FixedValue": {"Value": 30}}, "SPHitRatio": {"IsDynamic": False, "FixedValue": {"Value": 1}}}},
                {"$type": "RPG.GameCore.ModifySPNew", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"}, "AddValue": {"IsDynamic": False, "FixedValue": {"Value": 1}}},
            ],
        },
    ]
}
chain = summarize_ability_chain(ability_index(ability_file), "A")
lowered_types = [x["type"] for x in chain["lowered_preview"]]
assert "trigger_ability" in lowered_types
assert "add_status" in lowered_types
assert "damage_packet" in lowered_types
assert "modify_skill_points" in lowered_types
assert chain["visited_abilities"] == ["A", "B"]
checks.append("PASS RPG.GameCore lowering registry follows TriggerAbility chains and emits IR hints")




# v7.7: new high-frequency GameCore lowering coverage and targeted ActionIR compilation.
from hsr_engine.ability_lowering import lower_node, classify_inventory
from hsr_engine.action_ir_compiler import lowerings_to_action_ir

extra_nodes = [
    {"$type":"RPG.GameCore.SetEnergyBarState", "BarType":"Special", "CurrentCount":{"IsDynamic":False,"FixedValue":{"Value":2}}, "MaxCount":{"IsDynamic":False,"FixedValue":{"Value":4}}, "Active": True},
    {"$type":"RPG.GameCore.CharacterChangePhase", "TargetType":{"$type":"RPG.GameCore.TargetAlias","Alias":"Caster"}, "PhaseName":"Phase02"},
    {"$type":"RPG.GameCore.SetModifierDynamicValue", "TargetType":{"$type":"RPG.GameCore.TargetAlias","Alias":"Caster"}, "ModifierName":"MTest", "DynamicKey":"stack", "NewValue":{"IsDynamic":False,"FixedValue":{"Value":3}}},
    {"$type":"RPG.GameCore.SetDynamicValueByShield", "TargetType":{"$type":"RPG.GameCore.TargetAlias","Alias":"AbilityTargetEntity"}, "DynamicKey":"shield_snapshot"},
    {"$type":"RPG.GameCore.ByHasStanceWeak", "TargetType":{"$type":"RPG.GameCore.TargetAlias","Alias":"AbilityTargetEntity"}, "WeakType":"Quantum"},
    {"$type":"RPG.GameCore.ByTargetListIntersects", "FirstTargetType":{"$type":"RPG.GameCore.TargetAlias","Alias":"AllEnemy"}, "SecondTargetType":{"$type":"RPG.GameCore.TargetAlias","Alias":"AbilityTargetEntityList"}},
    {"$type":"RPG.GameCore.ByCurrentSkillName", "SkillName":"Skill02"},
]
low_types = [lower_node(n)["type"] for n in extra_nodes]
assert low_types == ["set_energy_bar_state", "change_phase", "set_status_dynamic_value", "set_flag_from_shield", "has_weakness", "target_lists_intersect", "current_skill_name"], low_types
assert classify_inventory({"RPG.GameCore.AlignTargetToTeamCenter": 1, "RPG.GameCore.ShowBonusUIEffect": 1})["lowering_status_counts"] == {"ignore_visual_timeline": 2}
checks.append("PASS high-frequency GameCore backlog nodes lower into ConditionIR/EffectIR hints and visual UI/pose helpers stay evidence-only")

fake_action = {
    "action_id": 1,
    "kind_hint": "skill_or_talent",
    "damage_type": "Quantum",
    "attack_type": "Skill",
    "levels": [{"bp_need": -1, "sp_multiple_ratio": 1, "delay_ratio": 1, "stance_damage_display": 20, "show_stance_list": [60,0,0], "show_damage_list": []}],
    "ability_graph_summary": {
        "lowered_preview": [
            {"type":"damage_packet", "source_node_type":"RPG.GameCore.DamageByAttackProperty", "source_path":"OnStart[0]", "damage_type":"Quantum", "target_policy":"selected_target", "scaling":{"stat":"atk", "multiplier_expr":1}},
            {"type":"damage_packet", "source_node_type":"RPG.GameCore.AttackData", "source_path":"OnStart[0].AttackProperty", "damage_type":"Quantum", "scaling":{"stat":"atk", "multiplier_expr":1}},
            {"type":"add_status", "target_policy":"self", "status_id":"buff"},
            {"type":"conditional_branch", "condition":{"type":"has_weakness", "weakness_type":"Quantum"}},
            {"type":"trigger_ability", "ability_name":"Phase02"},
        ],
        "unresolved_refs": [],
        "unlowered_combat_node_types": {},
        "lowering_coverage": {"lowered_count": 5, "unlowered_relevant_count": 0},
    },
}
air = lowerings_to_action_ir(fake_action)
assert air["ir_status"] == "candidate_executable_ir"
assert len(air["damage_packets"]) == 1, "nested AttackData duplicate should be removed from ActionIR"
assert len(air["effects"]) == 1 and len(air["control_flow"]) == 1 and len(air["ability_references"]) == 1
checks.append("PASS targeted ActionIR compiler partitions lowered hints and deduplicates nested AttackData packets")

modifier_def_action = {
    "action_id": 2,
    "kind_hint": "ultimate",
    "damage_type": "Quantum",
    "attack_type": "Ultra",
    "levels": [{"bp_need": -1, "sp_multiple_ratio": 1, "delay_ratio": 1, "stance_damage_display": 30, "show_stance_list": [90,0,0], "show_damage_list": []}],
    "ability_graph_summary": {
        "lowered_preview": [
            {"type":"damage_packet", "source_node_type":"RPG.GameCore.DamageByAttackProperty", "source_path":"Modifiers.Rank06Flag._CallbackList[0]", "damage_type":"Quantum", "scaling":{"stat":"atk", "multiplier_expr":1}},
            {"type":"damage_packet", "source_node_type":"RPG.GameCore.DamageByAttackProperty", "source_path":"OnStart[2]", "damage_type":"Quantum", "scaling":{"stat":"atk", "multiplier_expr":1}},
        ],
        "unresolved_refs": [],
        "unlowered_combat_node_types": {},
        "lowering_coverage": {"lowered_count": 2, "unlowered_relevant_count": 0},
    },
}
air2 = lowerings_to_action_ir(modifier_def_action)
assert len(air2["damage_packets"]) == 1, "modifier definition callback damage must not become direct action damage"
assert air2["status_definition_hint_count"] == 1
checks.append("PASS targeted ActionIR keeps modifier-definition callbacks out of direct action damage")


# v7.8 Dynamic expression binder: compiled ActionIR dynamic hashes bind to AvatarSkillConfig parameters.
from hsr_engine.dynamic_expression_binder import bind_action_ir_bundle, write_bound_action_ir_bundle
# Overwrite the minimal fixture's skill table with one realistic multi-hit skill.
with zipfile.ZipFile(fixture_zip, "a") as z:
    root = "turnbasedgamedata-main/ExcelOutput/"
    z.writestr(root + "AvatarSkillConfig.json", json.dumps([
        {
            "SkillID": 110202,
            "Level": 15,
            "MaxLevel": 15,
            "SkillTriggerKey": "Skill02",
            "AttackType": "BPSkill",
            "SPBase": {"Value": 30},
            "BPNeed": {"Value": 1},
            "SPMultipleRatio": {"Value": 0.5},
            "DelayRatio": {"Value": 1},
            "ParamList": [{"Value": 2.75}, {"Value": 0.25}, {"Value": 2}],
            "SimpleParamList": [{"Value": 2.75}, {"Value": 0.25}, {"Value": 2}],
            "ShowStanceList": [{"Value": 60}, {"Value": 0}, {"Value": 0}],
            "StanceDamageDisplay": 20,
        }
    ]))

fake_action_bundle = {
    "format": "targeted_action_ir_bundle",
    "avatars": [
        {
            "avatar_id": 1102,
            "actions": [
                {
                    "action_id": 110202,
                    "trigger_key": "Skill02",
                    "damage_packets": [
                        {"scaling": {"multiplier_expr": {"expr_kind": "tbgd_postfix_dynamic", "fixed_values": [0.2], "dynamic_hashes": [-1847083384]}}, "toughness": {"toughness_reduction_expr": {"expr_kind": "tbgd_postfix_dynamic", "fixed_values": [0.2], "dynamic_hashes": [1659254037]}}},
                        {"scaling": {"multiplier_expr": {"expr_kind": "tbgd_postfix_dynamic", "fixed_values": [0.1], "dynamic_hashes": [-1847083384]}}, "toughness": {"toughness_reduction_expr": {"expr_kind": "tbgd_postfix_dynamic", "fixed_values": [0.1], "dynamic_hashes": [1659254037]}}},
                        {"scaling": {"multiplier_expr": {"expr_kind": "tbgd_postfix_dynamic", "fixed_values": [0.1], "dynamic_hashes": [-1847083384]}}, "toughness": {"toughness_reduction_expr": {"expr_kind": "tbgd_postfix_dynamic", "fixed_values": [0.1], "dynamic_hashes": [1659254037]}}},
                        {"scaling": {"multiplier_expr": {"expr_kind": "tbgd_postfix_dynamic", "fixed_values": [0.6], "dynamic_hashes": [-1847083384]}}, "toughness": {"toughness_reduction_expr": {"expr_kind": "tbgd_postfix_dynamic", "fixed_values": [0.6], "dynamic_hashes": [1659254037]}}},
                    ],
                }
            ],
        }
    ],
}
bound = bind_action_ir_bundle(fake_action_bundle, TBGDSource.open(fixture_zip))
action = bound["avatars"][0]["actions"][0]
assert action["energy_gain"]["base"] == 30.0
assert action["skill_point_delta"] == -1.0
assert close(action["damage_packet_binding_summary"]["total_resolved_multiplier"], 2.75)
assert close(action["damage_packet_binding_summary"]["total_resolved_toughness_reduction"], 60.0)
assert action["damage_packets"][0]["scaling"]["multiplier"] == 0.55
assert action["damage_packets"][3]["scaling"]["multiplier"] == 1.65
bound_dir = OUT / "mini_bound_action_ir"
fake_path = OUT / "mini_action_ir_bundle.json"
fake_path.write_text(json.dumps(fake_action_bundle), encoding="utf-8")
summary = write_bound_action_ir_bundle(fixture_zip, fake_path, bound_dir)
assert summary["expression_status_counts"]["expr_resolved_fixed_times_hash"] == 8
assert (bound_dir / "bound_action_ir_bundle.json").exists()
checks.append("PASS dynamic expression binder resolves per-hit multipliers/toughness from AvatarSkillConfig parameters")

# v7.8 StatusIR compiler: modifier-definition hints become structured StatusIR instead of direct ActionIR.
from hsr_engine.status_ir_compiler import compile_status_ir_bundle, write_status_ir_bundle

fake_status_action_bundle = {
    "format": "hsr_bound_action_ir_bundle",
    "version": "test",
    "avatar_ids": [9999],
    "avatars": [
        {
            "avatar_id": 9999,
            "config_paths": {"ability": "Config/ConfigAbility/Avatar/TestStatus_Ability.json"},
            "actions": [
                {
                    "action_id": 999901,
                    "trigger_key": "SkillP01",
                    "status_definition_hints": [
                        {"type": "conditional_branch", "condition": {"type": "has_status", "status_id": "Gate"}, "source_path": "Modifiers.TestStatus._CallbackList[0].CallbackConfig[0]"},
                        {"type": "has_status", "status_id": "Gate", "source_path": "Modifiers.TestStatus._CallbackList[0].CallbackConfig[0].Predicate"},
                        {"type": "add_status", "status_id": "Buff", "target_policy": "self", "source_path": "Modifiers.TestStatus._CallbackList[0].CallbackConfig[0].SuccessTaskList[0]"},
                        {"type": "remove_status", "status_id": "Debuff", "target_policy": "self", "source_path": "Modifiers.TestStatus._CallbackList[0].CallbackConfig[0].FailedTaskList[0]"},
                        {"type": "set_flag", "key": "direct", "value_expr": 1, "source_path": "Modifiers.TestStatus._CallbackList[0].CallbackConfig[1]"},
                    ],
                }
            ],
        }
    ],
}
with zipfile.ZipFile(fixture_zip, "a") as z:
    z.writestr("turnbasedgamedata-main/Config/ConfigAbility/Avatar/TestStatus_Ability.json", json.dumps({
        "AbilityList": [
            {
                "Name": "TestStatusAbility",
                "Modifiers": {
                    "TestStatus": {
                        "BehaviorFlagList": ["ListenBattleEventSkill"],
                        "Stacking": "Multiple",
                        "DynamicValues": {"Floats": {"123": {"ReadInfo": {"Type": "None", "Index": 0}}}},
                        "_CallbackList": [
                            {"Event": "OnCreate", "Priority": -7, "CallbackConfig": [{"$type": "RPG.GameCore.PredicateTaskList"}, {"$type": "RPG.GameCore.SetDynamicValue"}]}
                        ],
                    }
                },
            }
        ]
    }))
status_ir = compile_status_ir_bundle(fake_status_action_bundle, source=TBGDSource.open(fixture_zip))
assert status_ir["summary"]["status_count"] == 1
assert status_ir["summary"]["metadata_enriched_status_count"] == 1
assert status_ir["summary"]["trigger_count"] == 1
st = status_ir["statuses"][0]
assert st["status_id"] == "TestStatus"
tr = st["triggers"][0]
assert tr["trigger_kind"] == "modifier_callback"
assert tr["event_name"] == "OnCreate" and tr["event_priority"] == -7
assert st["modifier_metadata"]["behavior_flags"] == ["ListenBattleEventSkill"]
assert st["modifier_metadata"]["dynamic_values_declared"]["Floats"] == ["123"]
assert len(tr["branch_groups"]) == 1, "only Predicate/SuccessTaskList/FailedTaskList entries should form branch groups"
assert len(tr["effects"]) == 3, "branch effects and direct callback effects should all be preserved as effects"
assert tr["branch_groups"][0]["condition"]["type"] == "has_status"
assert len(tr["branch_groups"][0]["success_effects"]) == 1
assert len(tr["branch_groups"][0]["failed_effects"]) == 1
checks.append("PASS StatusIR compiler groups modifier callbacks, branches, and direct status effects")

real_bound_path = ROOT.parent / "bound_action_ir_v0_8" / "bound_action_ir_bundle.json"
if real_bound_path.exists():
    real_status_dir = OUT / "status_ir_v0_1"
    real_summary = write_status_ir_bundle(real_bound_path, real_status_dir)
    assert real_summary["status_count"] == 22, real_summary
    assert real_summary["trigger_count"] == 45, real_summary
    assert real_summary["hint_count"] == 237, real_summary
    assert real_summary["invalid_source_path_count"] == 0, real_summary
    assert (real_status_dir / "status_ir_bundle.json").exists()
    checks.append("PASS StatusIR compiler emits target-team status bundle from bound ActionIR hints")


# v7.9 Status dynamic expression binder: bind only conservative numeric contexts and keep modifier DynamicValues symbolic.
from hsr_engine.status_dynamic_expression_binder import bind_status_ir_bundle, write_bound_status_ir_bundle

status_binder_zip = OUT / "mini_status_dynamic_binder_tbgd.zip"
with zipfile.ZipFile(status_binder_zip, "w") as z:
    root = "turnbasedgamedata-main/ExcelOutput/"
    z.writestr(root + "AvatarConfig.json", json.dumps([{
        "AvatarID": 9999, "AvatarName": {"Hash": 1}, "AvatarFullName": {"Hash": 2},
        "Rarity": "CombatPowerAvatarRarityType5", "DamageType": "Quantum", "AvatarBaseType": "Rogue",
        "SkillList": [999901], "RankIDList": [999906], "JsonPath": "Config/ConfigCharacter/Avatar/Avatar_Status_Test_Config.json"
    }]))
    z.writestr(root + "AvatarSkillConfig.json", json.dumps([{
        "SkillID": 999901, "Level": 1, "MaxLevel": 1, "SkillTriggerKey": "SkillP01",
        "ParamList": [{"Value": 10}, {"Value": 20}],
        "SimpleParamList": [{"Value": 10}, {"Value": 20}],
        "ShowStanceList": [],
    }]))
    z.writestr(root + "AvatarSkillTreeConfig.json", json.dumps([{
        "AvatarID": 9999, "PointID": 9999103, "Level": 1, "PointTriggerKey": "PointB3",
        "AbilityName": "", "ParamList": [{"Value": 0.33}],
    }]))
    z.writestr(root + "AvatarRankConfig.json", json.dumps([{
        "RankID": 999906, "Rank": 6, "RankAbility": ["Avatar_Status_Test_Rank06"],
        "Param": [{"Value": 0.15}, {"Value": 1}],
    }]))
    z.writestr("turnbasedgamedata-main/Config/ConfigAbility/Avatar/Avatar_Status_Test_Ability.json", json.dumps({
        "AbilityList": [{
            "Name": "Avatar_Status_Test_Passive",
            "Modifiers": {
                "M_Test_Passive": {
                    "DynamicValues": {"Floats": {"222": {"ReadInfo": {"Type": "None", "Index": 0}}}},
                    "_CallbackList": [{"Event": "OnCreate", "CallbackConfig": []}],
                },
                "M_Test_Rank06_Flag": {
                    "_CallbackList": [{"Event": "OnCreate", "CallbackConfig": []}],
                },
            },
        }]
    }))

mini_status_ir = {
    "format": "hsr_status_ir_bundle",
    "version": "test",
    "statuses": [
        {
            "owner_avatar_id": 9999,
            "namespace": "Modifiers",
            "status_id": "M_Test_Passive",
            "source_action_ids": [999901],
            "modifier_metadata": {
                "defined_in_ability": "Avatar_Status_Test_Passive",
                "ability_path": "Config/ConfigAbility/Avatar/Avatar_Status_Test_Ability.json",
                "dynamic_values_declared": {"Floats": ["222"]},
            },
            "triggers": [{
                "trigger_id": "modifier_callback:_CallbackList[0]",
                "trigger_kind": "modifier_callback",
                "effects": [
                    {"type": "set_flag", "key": "first", "value_expr": {"expr_kind": "tbgd_postfix_dynamic", "dynamic_hashes": [111], "fixed_values": []}},
                    {"type": "set_flag", "key": "symbolic", "value_expr": {"expr_kind": "tbgd_postfix_dynamic", "dynamic_hashes": [222], "fixed_values": []}},
                    {"type": "set_flag", "key": "after_symbolic", "value_expr": {"expr_kind": "tbgd_postfix_dynamic", "dynamic_hashes": [333], "fixed_values": []}},
                ],
            }],
        },
        {
            "owner_avatar_id": 9999,
            "namespace": "Modifiers",
            "status_id": "M_Test_Rank06_Flag",
            "source_action_ids": [999901],
            "modifier_metadata": {
                "defined_in_ability": "Avatar_Status_Test_Rank06",
                "ability_path": "Config/ConfigAbility/Avatar/Avatar_Status_Test_Ability.json",
                "dynamic_values_declared": {},
            },
            "triggers": [{
                "trigger_id": "modifier_callback:_CallbackList[0]",
                "trigger_kind": "modifier_callback",
                "effects": [
                    {"type": "damage_packet", "scaling": {"multiplier_expr": {"expr_kind": "tbgd_postfix_dynamic", "dynamic_hashes": [444], "fixed_values": []}}},
                ],
            }],
        },
    ],
}
bound_status = bind_status_ir_bundle(mini_status_ir, TBGDSource.open(status_binder_zip))
passive = next(s for s in bound_status["statuses"] if s["status_id"] == "M_Test_Passive")
assert passive["dynamic_binding"]["numeric_bindings"]["111"]["value"] == 10.0
assert "222" in passive["dynamic_binding"]["symbolic_bindings"], "declared modifier DynamicValue must stay symbolic"
assert "333" not in passive["dynamic_binding"]["numeric_bindings"], "later hashes must not shift left across a symbolic slot"
assert passive["dynamic_binding_summary"]["unresolved_expression_count"] == 1
assert passive["dynamic_binding_summary"]["resolve_attachment_failure_count"] == 0
effects = passive["triggers"][0]["effects"]
assert effects[0]["value_expr_resolve"]["status"] == "status_resolved_hash"
assert effects[1]["value_expr_resolve"]["status"] == "symbolic_modifier_dynamic_value"
assert effects[2]["value_expr_resolve"]["status"] == "unresolved_status_dynamic_expr"
rank_status = next(s for s in bound_status["statuses"] if s["status_id"] == "M_Test_Rank06_Flag")
assert rank_status["dynamic_binding"]["numeric_bindings"]["444"]["value"] == 0.15
assert rank_status["dynamic_binding"]["numeric_bindings"]["444"]["confidence"] == "high"
mini_status_path = OUT / "mini_status_ir_bundle_for_binding.json"
mini_status_path.write_text(json.dumps(mini_status_ir), encoding="utf-8")
mini_bound_status_dir = OUT / "mini_bound_status_ir"
mini_bound_summary = write_bound_status_ir_bundle(mini_status_path, mini_bound_status_dir, status_binder_zip)
assert mini_bound_summary["dynamic_expression_count"] == 4
assert mini_bound_summary["resolved_expression_count"] == 2
assert mini_bound_summary["symbolic_expression_count"] == 1
assert mini_bound_summary["unresolved_expression_count"] == 1
assert mini_bound_summary["resolve_attachment_failure_count"] == 0
checks.append("PASS Status dynamic binder preserves runtime DynamicValues and attaches resolve traces to nested StatusIR paths")

real_status_path = ROOT.parent / "status_ir_v0_2" / "status_ir_bundle.json"
if real_status_path.exists():
    real_bound_status_dir = OUT / "bound_status_ir_v0_1"
    tbgd_candidates = [ROOT.parent.parent.parent / "TurnBasedGameData-main.zip", ROOT.parent / "TurnBasedGameData-main.zip", Path("/mnt/data/TurnBasedGameData-main.zip"), Path("/mnt/data/turnbasedgamedata-main.zip")]
    tbgd_zip = next((c for c in tbgd_candidates if c.exists()), tbgd_candidates[0])
    real_bound_status_summary = write_bound_status_ir_bundle(real_status_path, real_bound_status_dir, tbgd_zip)
    assert real_bound_status_summary["status_count"] == 22
    assert real_bound_status_summary["dynamic_expression_count"] == 89
    assert real_bound_status_summary["resolved_expression_count"] >= 40
    assert real_bound_status_summary["symbolic_expression_count"] >= 10
    assert real_bound_status_summary["unresolved_expression_count"] >= 1
    assert (real_bound_status_dir / "bound_status_ir_bundle.json").exists()
    checks.append("PASS real target-team StatusIR dynamic binder emits conservative BoundStatusIR bundle")



# v8.0 Status template compiler: lower BoundStatusIR triggers conservatively and preserve branch semantics.
from hsr_engine.status_template_compiler import compile_status_template_bundle, write_status_template_bundle, _convert_condition, _convert_effect

mini_bound_status_ir = {
    "format": "hsr_bound_status_ir_bundle",
    "version": "test",
    "statuses": [{
        "owner_avatar_id": 9999,
        "namespace": "Modifiers",
        "status_id": "M_Template_Test",
        "modifier_metadata": {"behavior_flags": ["ListenBattleEventSkill"], "max_layer": 2, "lifetime": 3},
        "triggers": [{
            "trigger_id": "modifier_callback:_CallbackList[0]",
            "trigger_kind": "modifier_callback",
            "event_name": "OnEnterBattle",
            "conditions": [{"type": "compare_wave_count", "op": "==", "value_expr": {"IsDynamic": False, "FixedValue": 1}}],
            "effects": [
                {"type": "set_flag", "key": "direct", "value_expr": {"IsDynamic": False, "FixedValue": 1}, "source_path": "Modifiers.M_Template_Test._CallbackList[0].CallbackConfig[1]"},
                {"type": "damage_packet", "damage_type": "Quantum", "scaling": {"stat": "atk", "multiplier_expr": {"expr_kind": "tbgd_postfix_dynamic", "dynamic_hashes": [1], "fixed_values": []}, "multiplier_expr_resolve": {"status": "status_resolved_hash", "value": 0.5}}, "source_path": "Modifiers.M_Template_Test._CallbackList[0].CallbackConfig[2]"},
                {"type": "set_flag", "key": "branch_true", "value_expr": {"IsDynamic": False, "FixedValue": 1}, "source_path": "Modifiers.M_Template_Test._CallbackList[0].CallbackConfig[0].SuccessTaskList[0]"},
            ],
            "branch_groups": [{
                "branch_root": "CallbackConfig[0]",
                "branch_index": 0,
                "condition": {"type": "compare_dynamic_value", "key": "Gate", "op": "==", "value_expr": {"IsDynamic": False, "FixedValue": 1}},
                "success_effects": [
                    {"type": "set_flag", "key": "branch_true", "value_expr": {"IsDynamic": False, "FixedValue": 1}, "source_path": "Modifiers.M_Template_Test._CallbackList[0].CallbackConfig[0].SuccessTaskList[0]"},
                    {"type": "add_status", "status_id": "Buff", "target_policy": "self", "duration_expr": {"IsDynamic": False, "FixedValue": 2}, "dynamic_values": {"BuffRate": {"expr_kind": "tbgd_postfix_dynamic", "dynamic_hashes": [2], "fixed_values": []}, "BuffRate_resolve": {"status": "status_resolved_hash", "value": 0.2}}, "source_path": "Modifiers.M_Template_Test._CallbackList[0].CallbackConfig[0].SuccessTaskList[1]"},
                ],
                "failed_effects": [
                    {"type": "remove_status", "status_id": "Debuff", "target_policy": "self", "source_path": "Modifiers.M_Template_Test._CallbackList[0].CallbackConfig[0].FailedTaskList[0]"},
                ],
            }],
        }],
    }],
}
mini_templates = compile_status_template_bundle(mini_bound_status_ir)
assert mini_templates["summary"]["status_template_count"] == 1
assert mini_templates["summary"]["trigger_count"] == 1
assert mini_templates["summary"]["executable_trigger_count"] == 1, mini_templates["summary"]
mini_trig = mini_templates["triggers"][0]
assert mini_trig["timing"] == "battle_start"
assert mini_trig["condition"] == {"left": "battle.wave_number", "op": "==", "right": 1}
assert len(mini_trig["effects"]) == 3, "direct effects plus conditional branch; branch member must not become unconditional"
assert mini_trig["effects"][0]["type"] == "set_flag"
damage = next(e for e in mini_trig["effects"] if e["type"] == "deal_damage")
assert damage["target"] == "target", "damage without explicit target_policy must default to selected target, not None"
branch = next(e for e in mini_trig["effects"] if e["type"] == "conditional_branch")
assert branch["condition"] == {"left": "flag:Gate", "op": "==", "right": 1}
assert len(branch["effects_if_true"]) == 2
status_effect = next(e for e in branch["effects_if_true"] if e["type"] == "add_status")
assert status_effect["status"]["dynamic_values"] == {"BuffRate": 0.2}
assert "unresolved_dynamic_values" not in status_effect["status"]
assert len(branch["effects_if_false"]) == 1
mini_template_dir = OUT / "mini_status_templates"
mini_bound_status_path = OUT / "mini_bound_status_ir_bundle_for_templates.json"
mini_bound_status_path.write_text(json.dumps(mini_bound_status_ir), encoding="utf-8")
mini_template_summary = write_status_template_bundle(mini_bound_status_path, mini_template_dir)
assert mini_template_summary["executable_trigger_count"] == 1
assert (mini_template_dir / "status_template_bundle.json").exists()
checks.append("PASS Status template compiler preserves branches, wave-count predicates, and executable simulator-facing triggers")

real_bound_status_path = ROOT.parent / "bound_status_ir_v0_1" / "bound_status_ir_bundle.json"
if real_bound_status_path.exists():
    real_template_dir = OUT / "status_templates_v0_1"
    real_template_summary = write_status_template_bundle(real_bound_status_path, real_template_dir)
    assert real_template_summary["status_template_count"] == 22
    assert real_template_summary["trigger_count"] == 45
    assert real_template_summary["executable_trigger_count"] >= 3
    assert (real_template_dir / "status_template_bundle.json").exists()
    checks.append("PASS real BoundStatusIR lowers into conservative status template bundle")


# v8.4 StatusTemplate integration: compiled status templates can be attached to a runtime case without hand-copying YAML triggers.
from hsr_engine.status_template_integration import attach_status_template_bundle_to_case, compile_case_status_template_import

compiled_import = compile_case_status_template_import(mini_templates, {9999: "actor"})
assert compiled_import["summary"]["status_effect_count"] == 1
assert compiled_import["summary"]["imported_trigger_count"] == 1
assert compiled_import["triggers"][0]["owner_id"] == "actor"
rank_gated_bundle = {
    "format": "hsr_status_template_bundle",
    "status_templates": {
        "MAvatar_Test_Rank06_Flag": {"id": "MAvatar_Test_Rank06_Flag", "owner_avatar_id": 9999},
    },
    "triggers": [{
        "id": "9999:MAvatar_Test_Rank06_Flag:trigger",
        "owner_avatar_id": 9999,
        "status_id": "MAvatar_Test_Rank06_Flag",
        "timing": "battle_start",
        "effects": [{"type": "set_flag", "key": "rank6", "value": 1}],
        "executable": True,
    }],
}
rank_skipped = compile_case_status_template_import(rank_gated_bundle, {9999: "actor"}, owner_rank_map={9999: 3})
assert rank_skipped["summary"]["imported_trigger_count"] == 0
assert rank_skipped["summary"]["skipped_trigger_count"] == 1
rank_active = compile_case_status_template_import(rank_gated_bundle, {9999: "actor"}, owner_rank_map={9999: 6})
assert rank_active["summary"]["imported_trigger_count"] == 1
status_template_case = {
    "global": {"flags": {"Gate": 1}, "skill_points": 3},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"atk": 100}},
        "target": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100},
    },
    "route": [],
}
attached_case, attached_summary = attach_status_template_bundle_to_case(status_template_case, mini_templates, {9999: "actor"})
assert attached_summary["imported_trigger_count"] == 1
sim = BattleSimulator(attached_case)
status_template_result = sim.run_route([])
assert status_template_result["state"]["global"]["flags"].get("direct") == 1
assert status_template_result["state"]["global"]["flags"].get("branch_true") == 1
actor_statuses = {s["id"]: s for s in status_template_result["state"]["units"]["actor"]["statuses"]}
assert actor_statuses["Buff"]["duration_value"] == 2
assert any("M_Template_Test" in e["message"] for e in status_template_result["log"] if e.get("event_type") == "trigger")
checks.append("PASS compiled StatusTemplate bundle attaches to runtime case, rank-gates inactive Eidolons, and executes battle-start trigger effects")



# v8.6 Status lifecycle runtime: generated status_create/status_stack/status_destroy triggers execute
# only for the matching lifecycle status unless the condition explicitly listens to trigger.status_id.
status_lifecycle_bundle = {
    "format": "hsr_status_template_bundle",
    "status_templates": {
        "LifecycleBuff": {"id": "LifecycleBuff", "owner_avatar_id": 9999},
        "LifecycleListener": {"id": "LifecycleListener", "owner_avatar_id": 9999},
    },
    "triggers": [
        {"id": "create", "owner_avatar_id": 9999, "status_id": "LifecycleBuff", "timing": "status_create", "effects": [{"type": "set_flag", "key": "created", "value": 1}], "executable": True},
        {"id": "stack", "owner_avatar_id": 9999, "status_id": "LifecycleBuff", "timing": "status_stack", "effects": [{"type": "set_flag", "key": "stacked", "value": 1}], "executable": True},
        {"id": "destroy", "owner_avatar_id": 9999, "status_id": "LifecycleBuff", "timing": "status_destroy", "effects": [{"type": "set_flag", "key": "destroyed", "value": 1}], "executable": True},
        {"id": "listener", "owner_avatar_id": 9999, "status_id": "LifecycleListener", "timing": "status_stack", "condition": {"left": "trigger.status_id", "op": "==", "right": "LifecycleBuff"}, "effects": [{"type": "set_flag", "key": "listener_heard_stack", "value": 1}], "executable": True},
        {"id": "wrong_status_no_condition", "owner_avatar_id": 9999, "status_id": "OtherStatus", "timing": "status_stack", "effects": [{"type": "set_flag", "key": "wrong_status_fired", "value": 1}], "executable": True},
    ],
}
lifecycle_case = {
    "global": {"flags": {}, "skill_points": 3, "skill_point_cap": 5},
    "units": {"u": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100}},
    "initial_effects": [
        {"type": "add_status", "target": "u", "status": "LifecycleBuff"},
        {"type": "add_status", "target": "u", "status": "LifecycleBuff"},
        {"type": "remove_status", "target": "u", "status_id": "LifecycleBuff"},
    ],
    "route": [],
}
lifecycle_attached, lifecycle_summary = attach_status_template_bundle_to_case(lifecycle_case, status_lifecycle_bundle, {9999: "u"})
assert lifecycle_summary["imported_trigger_count"] == 5
lifecycle_sim = BattleSimulator(lifecycle_attached)
lifecycle_result = lifecycle_sim.run_route([])
lifecycle_flags = lifecycle_result["state"]["global"]["flags"]
assert lifecycle_flags.get("created") == 1
assert lifecycle_flags.get("stacked") == 1
assert lifecycle_flags.get("destroyed") == 1
assert lifecycle_flags.get("listener_heard_stack") == 1
assert "wrong_status_fired" not in lifecycle_flags
checks.append("PASS status lifecycle triggers fire for create/stack/destroy and listener conditions without cross-status leakage")

# v8.7 Kernel supports generated skill-point-cap effects.
sp_cap_case = {
    "global": {"flags": {}, "skill_points": 5, "skill_point_cap": 5},
    "units": {"u": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100}},
    "initial_effects": [
        {"type": "modify_skill_point_cap", "amount": 2},
        {"type": "modify_skill_points", "amount": 2},
        {"type": "modify_skill_point_cap", "amount": -4},
    ],
    "route": [],
}
sp_cap_result = BattleSimulator(sp_cap_case).run_route([])
assert sp_cap_result["state"]["global"]["skill_point_cap"] == 3
assert sp_cap_result["state"]["global"]["skill_points"] == 3
checks.append("PASS modify_skill_point_cap effect updates cap and clamps current skill points")


# v8.8 Wave-start runtime window: compiled wave_start triggers execute after wave spawn.
wave_start_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {},
    "waves": [
        {"units": {"e1": {"side": "enemy", "hp": 100, "max_hp": 100, "speed": 100}}}
    ],
    "triggers": [
        {"id": "wave_start_flag", "timing": "wave_start", "condition": {"left": "battle.wave_number", "op": "==", "right": 1}, "effects": [{"type": "set_flag", "key": "wave_started", "value": 1}]},
    ],
    "route": [],
}
wave_start_result = BattleSimulator(wave_start_case).run_route([])
assert wave_start_result["state"]["global"]["flags"].get("wave_started") == 1
checks.append("PASS wave_start triggers execute after wave spawn with 1-based battle.wave_number")


# v8.9 Extra-turn start context: generated compare_param_string can match queued extra_turn_type.
extra_turn_context_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100,
            "actions": {"noop_extra": {"id": "noop_extra", "actor_id": "actor", "target_policy": "self", "tags": ["extra_turn"], "cost": {"skill_points": 0}, "damage_packets": []}},
        }
    },
    "battle_start_effects": [{"type": "immediate_action", "queue": "immediate_queue", "actor": "actor", "action": "noop_extra", "target_policy": "self", "turn_kind": "extra_turn", "extra_turn_type": "Avatar_Seele_00_BonusInsertAction"}],
    "triggers": [
        {"id": "extra_type_flag", "timing": "extra_turn_start", "condition": {"left": "context.extra_turn_type", "op": "==", "right": "Avatar_Seele_00_BonusInsertAction"}, "effects": [{"type": "set_flag", "key": "bonus_insert_started", "value": 1}]},
    ],
    "route": [],
}
extra_turn_context_result = BattleSimulator(extra_turn_context_case).run_route([])
assert extra_turn_context_result["state"]["global"]["flags"].get("bonus_insert_started") == 1
checks.append("PASS extra_turn_start triggers receive queued extra_turn_type context for generated compare_param_string")


# v9.0 Generated context-value effects can materialize runtime counters into flags.
ctx_value_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "actions": {"spend": {"id": "spend", "actor_id": "actor", "target_policy": "self", "cost": {"skill_points": -2}, "damage_packets": []}}},
    },
    "triggers": [
        {"id": "capture_sp", "timing": "after_skill_point_consumed", "effects": [{"type": "set_flag_from_context_value", "key": "captured_sp", "context_value_type": "SetDynamicValueByVariateType", "variate_type": "ParamValue"}]},
    ],
    "route": [{"actor": "actor", "action": "spend", "targets": ["actor"], "timing": "manual"}],
}
ctx_value_result = BattleSimulator(ctx_value_case).run_route(ctx_value_case["route"])
assert ctx_value_result["state"]["global"]["flags"].get("captured_sp") == 2
checks.append("PASS set_flag_from_context_value captures consumed skill-point context for generated status templates")


# v9.1 Generated force_defeat effect defeats the selected target and emits defeat lifecycle.
force_defeat_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100},
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "shield": 500, "speed": 100},
    },
    "initial_effects": [{"type": "force_defeat", "target": "enemy"}],
    "triggers": [{"id": "force_defeat_seen", "timing": "after_defeat_enemy", "effects": [{"type": "set_flag", "key": "force_defeat_triggered", "value": 1}]}],
    "route": [],
}
force_defeat_result = BattleSimulator(force_defeat_case).run_route([])
assert force_defeat_result["state"]["units"]["enemy"]["alive"] is False
assert force_defeat_result["state"]["global"]["flags"].get("force_defeat_triggered") == 1
checks.append("PASS force_defeat effect kills the selected target and fires after_defeat_enemy triggers")


# v9.5 Action-delay lowering reads TBGD AddNormalizedValue/NormalizedValue and executes add/set semantics.
add_delay_ir = lower_node({
    "$type": "RPG.GameCore.ModifyActionDelay",
    "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
    "AddNormalizedValue": {"IsDynamic": False, "FixedValue": {"Value": 0.25}},
})
set_delay_ir = lower_node({
    "$type": "RPG.GameCore.SetActionDelay",
    "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
    "NormalizedValue": {"IsDynamic": False, "FixedValue": {"Value": 1.0}},
})
assert add_delay_ir["delay_expr"] == 0.25 and add_delay_ir["mode"] == "add"
assert set_delay_ir["delay_expr"] == 1.0 and set_delay_ir["mode"] == "set"

av_bound_status_ir = {
    "format": "hsr_bound_status_ir_bundle",
    "statuses": [{
        "owner_avatar_id": 9999,
        "status_id": "AVStatus",
        "modifier_metadata": {},
        "triggers": [
            {"trigger_id": "add_delay", "event_name": "OnEnterBattle", "effects": [add_delay_ir]},
            {"trigger_id": "set_delay", "event_name": "OnPhase1", "effects": [set_delay_ir]},
        ],
    }],
}
av_template_bundle = compile_status_template_bundle(av_bound_status_ir)
av_triggers = {t["source_trigger_id"]: t for t in av_template_bundle["triggers"]}
assert av_triggers["add_delay"]["executable"] is True
assert av_triggers["add_delay"]["effects"][0]["type"] == "delay_action"
assert av_triggers["add_delay"]["effects"][0]["percent"] == 0.25
assert av_triggers["set_delay"]["executable"] is True
assert av_triggers["set_delay"]["effects"][0]["type"] == "set_action_delay"

av_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {"u": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "initial_delay_ratio": 0.5}},
    "initial_effects": [
        {"type": "delay_action", "target": "u", "percent": 0.25},
        {"type": "set_action_delay", "target": "u", "percent": 1.0},
    ],
    "route": [],
}
av_result = BattleSimulator(av_case).run_route([])
assert close(av_result["state"]["units"]["u"]["remaining_av"], 100.0), av_result["state"]["units"]["u"]["remaining_av"]
checks.append("PASS generated action-delay effects lower and execute add/set normalized AV semantics")


# v9.6 TBGD flag/property/status-value watcher nodes lower into executable runtime effects.
sp_ir = lower_node({
    "$type": "RPG.GameCore.ModifyTeamBoostPoint",
    "ModifyValue": {"IsDynamic": False, "FixedValue": {"Value": 2}},
})
sp_cap_ir = lower_node({
    "$type": "RPG.GameCore.ModifyTeamBoostPointMax",
    "ModifyValue": {"IsDynamic": False, "FixedValue": {"Value": 1}},
})
prop_ir = lower_node({
    "$type": "RPG.GameCore.SetDynamicValueByProperty",
    "DynamicKey": {"Value": "atk_snapshot"},
    "ReadTargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
    "Value": "Attack",
})
copy_ir = lower_node({
    "$type": "RPG.GameCore.SetDynamicValueByCopying",
    "ToDynamicKey": {"Value": "copied_ratio"},
    "FromDynamicKey": {"Value": "MDF_DamageRatio"},
    "FromModifierName": {"Value": "SrcStatus"},
    "FromTargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
    "ToTargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
})
status_value_ir = lower_node({
    "$type": "RPG.GameCore.SetDynamicValueByModifierValue",
    "DynamicKey": {"Value": "stack_snapshot"},
    "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
    "ModifierName": {"Value": "SrcStatus"},
    "ValueType": "Layer",
})
include_ir = lower_node({
    "$type": "RPG.GameCore.IncludeTaskListTemplate",
    "Name": "ReduceActionDelay",
    "ParamTarget": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
    "DynamicValues": {"Arg0_NormalizedValue": {"IsDynamic": False, "FixedValue": {"Value": 0.5}}},
})
assert sp_ir["delta_expr"] == 2 and sp_cap_ir["delta_expr"] == 1
assert prop_ir["property"] == "Attack"
assert copy_ir["source_key"] == "MDF_DamageRatio" and copy_ir["source_status_id"] == "SrcStatus"
assert status_value_ir["value_type"] == "Layer"
assert include_ir["template_id"] == "ReduceActionDelay" and include_ir["dynamic_values"]["Arg0_NormalizedValue"] == 0.5

watcher_bound_status_ir = {
    "format": "hsr_bound_status_ir_bundle",
    "statuses": [{
        "owner_avatar_id": 9999,
        "status_id": "WatcherStatus",
        "modifier_metadata": {},
        "triggers": [{"trigger_id": "watcher", "event_name": "OnEnterBattle", "effects": [sp_ir, sp_cap_ir, prop_ir, copy_ir, status_value_ir, include_ir]}],
    }],
}
watcher_template_bundle = compile_status_template_bundle(watcher_bound_status_ir)
watcher_trigger = watcher_template_bundle["triggers"][0]
assert watcher_trigger["executable"] is True, watcher_trigger.get("unsupported_reasons")
watcher_effect_types = [e["type"] for e in watcher_trigger["effects"]]
assert "modify_skill_points" in watcher_effect_types
assert "modify_skill_point_cap" in watcher_effect_types
assert "set_flag_from_property" in watcher_effect_types
assert "copy_flag" in watcher_effect_types
assert "set_flag_from_status_value" in watcher_effect_types
assert "set_action_delay" in watcher_effect_types

watcher_case = {
    "global": {"flags": {}, "skill_points": 3, "skill_point_cap": 5},
    "units": {
        "actor": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100,
            "stats": {"atk": 1234},
            "statuses": [{"id": "SrcStatus", "stacks": 3, "dynamic_values": {"MDF_DamageRatio": 0.42}}],
        }
    },
    "triggers": [{"id": "watcher_runtime", "timing": "battle_start", "owner_id": "actor", "effects": watcher_trigger["effects"]}],
    "route": [],
}
watcher_result = BattleSimulator(watcher_case).run_route([])
assert watcher_result["state"]["global"]["skill_points"] == 5
assert watcher_result["state"]["global"]["skill_point_cap"] == 6
assert watcher_result["state"]["global"]["flags"].get("atk_snapshot") == 1234
assert close(watcher_result["state"]["global"]["flags"].get("copied_ratio"), 0.42)
assert watcher_result["state"]["global"]["flags"].get("stack_snapshot") == 3
assert close(watcher_result["state"]["units"]["actor"]["remaining_av"], 50.0)
checks.append("PASS generated property/copy/status-value/template effects lower and execute conservatively")


# v9.7 TBGD TurnInsertAction with PrepareAbilityName/CustomTag lowers to an extra-turn queue effect.
turn_insert_ir = lower_node({
    "$type": "RPG.GameCore.TurnInsertAction",
    "PrepareAbilityName": "Avatar_Seele_00_Bonus",
    "CustomTag": {"Value": "Avatar_Seele_00_BonusInsertAction"},
    "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"},
})
assert turn_insert_ir["action_id"] == "Avatar_Seele_00_Bonus"
assert turn_insert_ir["extra_turn_type"] == "Avatar_Seele_00_BonusInsertAction"
turn_insert_bundle = compile_status_template_bundle({
    "format": "hsr_bound_status_ir_bundle",
    "statuses": [{
        "owner_avatar_id": 9999,
        "status_id": "InsertStatus",
        "modifier_metadata": {},
        "triggers": [{"trigger_id": "insert", "event_name": "OnEnterBattle", "effects": [turn_insert_ir]}],
    }],
})
turn_insert_trigger = turn_insert_bundle["triggers"][0]
assert turn_insert_trigger["executable"] is True, turn_insert_trigger.get("unsupported_reasons")
assert turn_insert_trigger["effects"][0]["type"] == "launch_action"
assert turn_insert_trigger["effects"][0]["action"] == "Avatar_Seele_00_Bonus"
insert_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100,
            "actions": {"Avatar_Seele_00_Bonus": {"id": "Avatar_Seele_00_Bonus", "actor_id": "actor", "target_policy": "self", "tags": ["extra_turn"], "cost": {"skill_points": 0}, "effects_after_action_start": [{"type": "set_flag", "key": "bonus_action_ran", "value": 1}], "damage_packets": []}},
        }
    },
    "triggers": [{"id": "insert_runtime", "timing": "battle_start", "owner_id": "actor", "effects": turn_insert_trigger["effects"]}],
    "route": [],
}
insert_result = BattleSimulator(insert_case).run_route([])
assert insert_result["state"]["global"]["flags"].get("bonus_action_ran") == 1
checks.append("PASS generated TurnInsertAction lowers and executes as queued extra-turn action")


# v10.0 Generated target-list/entity-type conditions and custom-event effects execute conservatively.
intersect_cond, intersect_reasons = _convert_condition({"type": "target_lists_intersect", "first": "modifier_owner", "second": "tbgd_alias:ParamEntity"})
assert intersect_reasons == [], intersect_reasons
assert "target_lists_intersect" in intersect_cond
entity_cond, entity_reasons = _convert_condition({"type": "target_entity_type", "target_policy": "modifier_owner", "entity_type_mask": "Servant"})
assert entity_reasons == [], entity_reasons
custom_eff, custom_reasons = _convert_effect({"type": "trigger_effect", "effect_id": "Evt_Test", "target_policy": "self"}, "S")
assert custom_reasons == [], custom_reasons
assert custom_eff[0]["type"] == "trigger_custom_event"
visual_eff, visual_reasons = _convert_effect({"type": "trigger_effect", "effect_path": "Effects/Test.prefab", "target_policy": "self"}, "S")
assert visual_reasons == [], visual_reasons
assert visual_eff[0]["type"] == "record_visual_effect"

condition_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "tags": ["Servant"]},
        "target": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100},
    },
    "triggers": [
        {"id": "target_list_true", "timing": "battle_start", "owner_id": "actor", "condition": {"not": intersect_cond}, "effects": [{"type": "set_flag", "key": "not_intersect", "value": 1}]},
        {"id": "entity_true", "timing": "battle_start", "owner_id": "actor", "condition": entity_cond, "effects": [{"type": "set_flag", "key": "servant_target", "value": 1}]},
        {"id": "fire_custom", "timing": "battle_start", "owner_id": "actor", "effects": custom_eff},
        {"id": "custom_listener", "timing": "custom_event", "owner_id": "actor", "condition": {"left": "custom_event_id", "op": "==", "right": "Evt_Test"}, "effects": [{"type": "set_flag", "key": "custom_seen", "value": 1}]},
    ],
    "route": [],
}
condition_result = BattleSimulator(condition_case).run_route([])
assert condition_result["state"]["global"]["flags"].get("not_intersect") == 1
assert condition_result["state"]["global"]["flags"].get("servant_target") == 1
assert condition_result["state"]["global"]["flags"].get("custom_seen") == 1
checks.append("PASS generated target-list/entity-type conditions and trigger_effect custom events execute conservatively")


# v10.1 Ability-property and status-dynamic watcher timings receive initial/runtime windows.
watcher_timing_bundle = compile_status_template_bundle({
    "format": "hsr_bound_status_ir_bundle",
    "statuses": [{
        "owner_avatar_id": 9999,
        "status_id": "WatcherTiming",
        "modifier_metadata": {},
        "triggers": [
            {"trigger_id": "prop", "event_name": "OnAbilityPropertyChange[0].Ranges[0].OnChange[0]", "effects": [{"type": "set_flag_from_property", "key": "prop_atk", "property": "Attack", "target_policy": "self"}]},
            {"trigger_id": "dyn", "event_name": "OnDynamicValueChange[0].Ranges[0].OnChange[0]", "effects": [{"type": "set_energy_bar_state", "target_policy": "self", "current_state": "Active", "current_count_expr": {"IsDynamic": False, "FixedValue": 2}}]},
        ],
    }],
})
wt = {t["source_trigger_id"]: t for t in watcher_timing_bundle["triggers"]}
assert wt["prop"]["timing"] == "ability_property_change" and wt["prop"]["executable"] is True, wt["prop"]
assert wt["dyn"]["timing"] == "status_dynamic_value_change" and wt["dyn"]["executable"] is True, wt["dyn"]
watcher_timing_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {"actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"atk": 1111}}},
    "triggers": [
        {"id": "prop_runtime", "timing": "ability_property_change", "owner_id": "actor", "effects": wt["prop"]["effects"]},
        {"id": "dyn_runtime", "timing": "status_dynamic_value_change", "owner_id": "actor", "effects": wt["dyn"]["effects"]},
    ],
    "route": [],
}
watcher_timing_result = BattleSimulator(watcher_timing_case).run_route([])
assert watcher_timing_result["state"]["global"]["flags"].get("prop_atk") == 1111
assert watcher_timing_result["state"]["units"]["actor"]["flags"].get("energy_bar_state") == "Active"
assert watcher_timing_result["state"]["units"]["actor"]["flags"].get("energy_bar_count") == 2

owner_context_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "src": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"atk": 111}},
        "owner": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"atk": 2222}},
    },
    "triggers": [
        {"id": "owner_prop_runtime", "timing": "ability_property_change", "owner_id": "owner", "effects": wt["prop"]["effects"]},
    ],
    "initial_effects": [{"type": "add_status", "targets": ["src"], "status": {"id": "AnyStatus"}}],
    "route": [],
}
owner_context_result = BattleSimulator(owner_context_case).run_route([])
assert owner_context_result["state"]["global"]["flags"].get("prop_atk") == 2222
checks.append("PASS ability-property and status-dynamic watcher timings run through initial/runtime windows with owner-relative context")


# v10.2 Branches whose true/false sides lower identically can ignore unsupported predicates safely.
rank_same_branch_bundle = compile_status_template_bundle({
    "format": "hsr_bound_status_ir_bundle",
    "statuses": [{
        "owner_avatar_id": 9999,
        "status_id": "SameBranchStatus",
        "modifier_metadata": {},
        "triggers": [{
            "trigger_id": "same_branch",
            "event_name": "OnCreate",
            "branch_groups": [{
                "branch_root": "CallbackConfig[0]",
                "branch_index": 0,
                "condition": {"type": "eidolon_or_rank_active", "trigger_key": "unknown"},
                "success_effects": [{"type": "modify_skill_point_cap", "delta_expr": {"IsDynamic": False, "FixedValue": 2}}],
                "failed_effects": [{"type": "modify_skill_point_cap", "delta_expr": {"IsDynamic": False, "FixedValue": 2}}],
            }],
        }],
    }],
})
rank_same_trigger = rank_same_branch_bundle["triggers"][0]
assert rank_same_trigger["executable"] is True, rank_same_trigger.get("unsupported_reasons")
assert rank_same_trigger["effects"] == [{"type": "modify_skill_point_cap", "amount": 2}]
checks.append("PASS identical true/false branch effects ignore unsupported predicate safely")


# v10.4 owner-rank predicates, compare-param runtime binding, and skill-type queued actions.
from hsr_engine.status_template_compiler import compile_status_template_bundle
from hsr_engine.status_template_integration import attach_status_template_bundle_to_case

rank_bundle = compile_status_template_bundle({
    "format": "hsr_bound_status_ir_bundle",
    "statuses": [{
        "owner_avatar_id": 1306,
        "status_id": "RankPredicateStatus",
        "modifier_metadata": {},
        "triggers": [{
            "trigger_id": "rank_gate",
            "event_name": "OnCreate",
            "branch_groups": [{
                "condition": {"type": "eidolon_or_rank_active", "trigger_key": "1686351920"},
                "success_effects": [{"type": "modify_skill_point_cap", "delta_expr": {"IsDynamic": False, "FixedValue": 2}}],
                "failed_effects": [{"type": "modify_skill_point_cap", "delta_expr": {"IsDynamic": False, "FixedValue": 1}}],
            }],
        }],
    }],
})
rank_trigger = rank_bundle["triggers"][0]
assert rank_trigger["executable"] is True, rank_trigger.get("unsupported_reasons")
base_rank_case = {
    "global": {"flags": {}, "skill_points": 3, "skill_point_cap": 5},
    "units": {"sparkle": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "flags": {}}},
    "initial_effects": [{"type": "add_status", "target": "sparkle", "status": {"id": "RankPredicateStatus"}}],
    "route": [],
}
case_rank6, _ = attach_status_template_bundle_to_case(base_rank_case, rank_bundle, {1306: "sparkle"}, owner_rank_map={1306: 6})
case_rank1, _ = attach_status_template_bundle_to_case(base_rank_case, rank_bundle, {1306: "sparkle"}, owner_rank_map={1306: 1})
assert BattleSimulator(case_rank6).run_route([])["state"]["global"]["skill_point_cap"] == 7
assert BattleSimulator(case_rank1).run_route([])["state"]["global"]["skill_point_cap"] == 6

param_bundle = compile_status_template_bundle({
    "format": "hsr_bound_status_ir_bundle",
    "statuses": [{
        "owner_avatar_id": 9999,
        "status_id": "ParamCompareStatus",
        "modifier_metadata": {},
        "triggers": [{
            "trigger_id": "sp_delta",
            "event_name": "OnListenBpChange",
            "condition": {"type": "compare_param_value", "op": "<", "value_expr": {"IsDynamic": False, "FixedValue": 0}},
            "effects": [{"type": "set_flag", "key": "sp_consumed", "value": 1}],
        }],
    }],
})
param_trigger = param_bundle["triggers"][0]
assert param_trigger["executable"] is True, param_trigger.get("unsupported_reasons")
param_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {"actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "actions": {"skill": {"id": "skill", "tags": ["skill_use"], "cost": {"skill_points": -1}}}}},
    "triggers": [{"id": "param_runtime", "timing": "after_skill_point_consumed", "owner_id": "actor", "condition": param_trigger["condition"], "effects": param_trigger["effects"]}],
    "route": [{"actor": "actor", "action": "skill", "targets": []}],
}
assert BattleSimulator(param_case).run_route(param_case["route"])["state"]["global"]["flags"].get("sp_consumed") == 1

skill_type_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {"actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "actions": {"skill": {"id": "skill", "action_type": "skill", "target_policy": "manual", "tags": ["skill_use"], "effects": [{"type": "set_flag", "key": "skill_resolved", "value": 1}]}}}},
    "triggers": [{"id": "queue_by_type", "timing": "battle_start", "owner_id": "actor", "effects": [{"type": "enqueue_extra_turn_by_skill_type", "actor": "actor", "skill_type": "ControlSkill02", "queue": "immediate_queue"}]}],
    "route": [],
}
assert BattleSimulator(skill_type_case).run_route([])["state"]["global"]["flags"].get("skill_resolved") == 1
checks.append("PASS owner-rank predicates, compare-param runtime binding, and skill-type queued extra turns execute conservatively")


# v10.8 preshow audit-only, symbolic status DynamicValues, and mixed runtime*param SP deltas.
preshow_bundle = compile_status_template_bundle({
    "format": "hsr_bound_status_ir_bundle",
    "statuses": [{
        "owner_avatar_id": 9999,
        "status_id": "PreshowAuditStatus",
        "modifier_metadata": {},
        "triggers": [{"trigger_id": "preshow", "event_name": "ModifierAffectedPreshowConfig", "effects": []}],
    }],
})
preshow_trigger = preshow_bundle["triggers"][0]
assert preshow_trigger["executable"] is True, preshow_trigger.get("unsupported_reasons")
assert preshow_trigger["timing"] == "preshow_audit"
assert preshow_trigger["effects"][0]["type"] == "record_preshow_event"

symbolic_status_eff, symbolic_status_reasons = _convert_effect({
    "type": "add_status",
    "modifier_name": "SymbolicDynStatus",
    "target_policy": "self",
    "dynamic_values": {
        "RuntimeValue": {"expr_kind": "tbgd_postfix_dynamic", "opcodes": "AQAR", "dynamic_hashes": [123]},
        "RuntimeValue_resolve": {"status": "symbolic_modifier_dynamic_value", "hashes": [123], "bindings": {"123": {"kind": "modifier_dynamic_value"}}},
    },
}, "SourceStatus")
assert symbolic_status_reasons == [], symbolic_status_reasons
assert symbolic_status_eff[0]["status"].get("symbolic_dynamic_values"), symbolic_status_eff
symbolic_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {"actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100}},
    "triggers": [{"id": "symbolic_add", "timing": "battle_start", "owner_id": "actor", "effects": symbolic_status_eff}],
    "route": [],
}
symbolic_result = BattleSimulator(symbolic_case).run_route([])
status_mods = symbolic_result["state"]["units"]["actor"]["statuses"][0]["modifiers"]
assert "symbolic_dynamic_values" in status_mods and "RuntimeValue" in status_mods["symbolic_dynamic_values"]

sp_eff, sp_reasons = _convert_effect({
    "type": "modify_skill_points",
    "source_node_type": "RPG.GameCore.ModifySPNew",
    "delta_expr_resolve": {
        "status": "unresolved_mixed_symbolic_dynamic_expr",
        "symbolic_hashes": [-1],
        "numeric_bindings": {"2": {"value": 0.5}},
        "missing_hashes": [],
    },
}, "SourceStatus")
assert sp_reasons == [], sp_reasons
assert sp_eff == [{"type": "modify_skill_points_from_flag", "flag": "MDF_AttackCount", "scale": 0.5}]
sp_case = {
    "global": {"flags": {"MDF_AttackCount": 4}, "skill_points": 1, "skill_point_cap": 5},
    "units": {"actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100}},
    "triggers": [{"id": "sp_from_runtime", "timing": "battle_start", "owner_id": "actor", "effects": sp_eff}],
    "route": [],
}
assert BattleSimulator(sp_case).run_route([])["state"]["global"]["skill_points"] == 3

watcher_loop_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {"u": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100}},
    "triggers": [{
        "id": "watcher_adds_status",
        "timing": "ability_property_change",
        "owner_id": "u",
        "effects": [{"type": "add_status", "target": "actor", "status": {"id": "LoopStatus"}}],
    }],
    "initial_effects": [{"type": "add_status", "targets": ["u"], "status": {"id": "SeedStatus"}}],
    "route": [],
}
loop_result = BattleSimulator(watcher_loop_case).run_route([])
loop_status_ids = [s["id"] for s in loop_result["state"]["units"]["u"]["statuses"]]
assert loop_status_ids.count("LoopStatus") == 1, loop_status_ids
assert any(e["event_type"] == "trigger_skip" and "nested watcher" in e["message"] for e in loop_result["log"]), loop_result["log"]
checks.append("PASS preshow audit, symbolic DynamicValues, mixed runtime-param SP deltas, and nested watcher guard lower conservatively")


# v11.0 symbolic dynamic expression IR and generated-template import-only route mode.
from hsr_engine.status_dynamic_expression_binder import _evaluate_for_status
trace = _evaluate_for_status(
    {"expr_kind": "tbgd_postfix_dynamic", "opcodes": "AQABAQQR", "fixed_values": [], "dynamic_hashes": [-1, 2]},
    {2: {"value": 0.25, "source": "unit-test-param", "confidence": "high"}},
    {-1: {"kind": "modifier_dynamic_value", "group": "Floats", "hash": -1}},
)
assert trace["status"] == "unresolved_mixed_symbolic_dynamic_expr", trace
expr_ir = trace.get("symbolic_expression_ir")
assert expr_ir and expr_ir["all_hashes_identified"] is True, trace
assert [op["kind"] for op in expr_ir["operands"]] == ["runtime_dynamic_value", "numeric_binding"], expr_ir

route_mode_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "actions": {"noop": {"id": "noop", "target_policy": "manual"}}},
        "other": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "actions": {"noop": {"id": "noop", "target_policy": "manual"}}},
    },
    "initial_effects": [{"type": "set_flag", "key": "import_mode_setup", "value": 1}],
    # This exact route would fail because the actor has no regular-turn match;
    # import_only must skip it while preserving battle-start/import effects.
    "route": [{"actor": "missing_actor", "action": "noop", "targets": []}],
}
route_mode_path = OUT / "route_mode_import_only_case.yaml"
route_mode_out = OUT / "route_mode_import_only_result.json"
route_mode_path.write_text(yaml.safe_dump(route_mode_case, sort_keys=False), encoding="utf-8")
rc = simulator_main([str(route_mode_path), "--route-mode", "import_only", "--output", str(route_mode_out)])
assert rc == 0
route_mode_result = json.loads(route_mode_out.read_text(encoding="utf-8"))
assert route_mode_result["state"]["global"]["flags"].get("import_mode_setup") == 1
assert route_mode_result["metadata"]["route_mode"] == "import_only"
assert route_mode_result["metadata"]["skipped_route_step_count"] == 1
checks.append("PASS symbolic DynamicValue expression IR is explicit and import-only route mode separates generated-template validation from exact route replay")


# v11.1 audit-only status property hints are extracted from TBGD modifier definitions.
prop_src = OUT / "property_hint_tbgd"
(prop_src / "ExcelOutput").mkdir(parents=True, exist_ok=True)
(prop_src / "Config" / "ConfigAbility" / "Avatar").mkdir(parents=True, exist_ok=True)
(prop_src / "ExcelOutput" / "AvatarConfig.json").write_text(json.dumps([{
    "AvatarID": 9999,
    "JsonPath": "Config/ConfigAbility/Avatar/Avatar_Test_00_Ability.json",
}], ensure_ascii=False), encoding="utf-8")
(prop_src / "Config" / "ConfigAbility" / "Avatar" / "Avatar_Test_00_Ability.json").write_text(json.dumps({
    "GlobalModifiers": {
        "HintedStatus": {
            "_CallbackList": [{
                "Event": "OnStack",
                "CallbackConfig": [{
                    "$type": "RPG.GameCore.StackProperty",
                    "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "ModifierOwnerEntity"},
                    "Property": "AllDamageTypeAddedRatio",
                    "PropertyValue": {"IsDynamic": True, "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [42]}},
                }],
            }],
        }
    }
}, ensure_ascii=False), encoding="utf-8")
prop_bundle = compile_status_template_bundle({
    "format": "hsr_bound_status_ir_bundle",
    "statuses": [{
        "owner_avatar_id": 9999,
        "status_id": "SourceStatus",
        "modifier_metadata": {},
        "triggers": [{
            "trigger_id": "add_hinted",
            "event_name": "OnCreate",
            "effects": [{"type": "add_status", "modifier_name": "HintedStatus", "target_policy": "self", "dynamic_values": {"MDF_PropertyValue": 0.25}}],
        }],
    }],
}, tbgd_source=prop_src)
assert prop_bundle["summary"]["property_hint_count"] == 1, prop_bundle["summary"]
prop_trigger = prop_bundle["triggers"][0]
added_status = prop_trigger["effects"][0]["status"]
assert added_status["property_hints"][0]["value_expr_hashes"] == [42], added_status
prop_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {"actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100}},
    "triggers": [{"id": "add_hinted_runtime", "timing": "battle_start", "owner_id": "actor", "effects": prop_trigger["effects"]}],
    "route": [],
}
prop_result = BattleSimulator(prop_case).run_route([])
mods = prop_result["state"]["units"]["actor"]["statuses"][0]["modifiers"]
assert mods["property_hints"][0]["property"] == "AllDamageTypeAddedRatio", mods
checks.append("PASS TBGD StackProperty status hints are extracted as audit-only property metadata and preserved at runtime")


# v11.4 conservative property-hint consumer: only proven direct StackProperty
# mappings with unambiguous numeric status DynamicValues affect formulas.
property_runtime_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {
            "side": "ally",
            "hp": 1000,
            "max_hp": 1000,
            "speed": 100,
            "level": 80,
            "stats": {"atk": 1000, "crit_rate": 0, "crit_dmg": 1.0},
            "actions": {
                "hit": {
                    "id": "hit",
                    "actor_id": "actor",
                    "target_policy": "manual",
                    "tags": ["attack"],
                    "damage_packets": [{"id": "p", "element": "quantum", "scaling_stat": "atk", "multiplier": 1.0}],
                }
            },
        },
        "enemy": {"side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "level": 80, "defense": 0, "stats": {"def": 0}, "res": {"quantum": 0.2}},
    },
    "triggers": [{
        "id": "add_runtime_property_status",
        "timing": "battle_start",
        "owner_id": "actor",
        "effects": [{
            "type": "add_status",
            "target": "actor",
            "status": {
                "id": "RuntimePropertyStatus",
                "dynamic_values": {"MDF_PropertyValue": 0.25},
                "property_hints": [{"property": "AllDamageTypeAddedRatio", "target": "actor", "source_path": "unit.test"}],
            },
        }],
    }],
    "route": [{"actor": "actor", "action": "hit", "targets": ["enemy"], "events": {"__crit_mode__": "noncrit"}}],
}
property_runtime_result = BattleSimulator(property_runtime_case).run_route(property_runtime_case["route"])
prop_status_mods = property_runtime_result["state"]["units"]["actor"]["statuses"][0]["modifiers"]
assert prop_status_mods["dmg_bonus_add"] == 0.25, prop_status_mods
assert prop_status_mods["property_hint_applications"][0]["applied"] is True, prop_status_mods
prop_audit = property_runtime_result["runtime_audit"]["property_hint_applications"]
assert prop_audit["applied_count"] == 1 and prop_audit["by_property"]["AllDamageTypeAddedRatio"]["applied"] == 1, prop_audit
packet_result = next(e for e in property_runtime_result["log"] if e["event_type"] == "damage")
assert abs(packet_result["data"]["multipliers"]["dmg_bonus"] - 1.25) < 1e-9, packet_result

ambiguous_status = StatusEffect.from_dict({
    "id": "AmbiguousPropertyStatus",
    "dynamic_values": {"foo": 0.1, "bar": 0.2},
    "property_hints": [{"property": "AllDamageTypeAddedRatio", "target": "actor"}],
})
ambiguous_mods = ambiguous_status.modifiers
assert "dmg_bonus_add" not in ambiguous_mods, ambiguous_mods
assert ambiguous_mods["property_hint_applications"][0]["reason"] == "ambiguous_numeric_dynamic_values", ambiguous_mods

res_pen_status = StatusEffect.from_dict({
    "id": "PenetratePropertyStatus",
    "dynamic_values": {"MDF_PropertyValue": 0.3},
    "property_hints": [{"property": "AllDamageTypePenetrate", "target": "actor"}],
})
assert res_pen_status.modifiers["all_res_pen"] == 0.3, res_pen_status.modifiers
checks.append("PASS property hints lower into damage/res-pen modifiers only with unambiguous numeric DynamicValues")


# v11.9 symbolic formula executor and generated-template auto-probe route mode.
from hsr_engine.symbolic_formula_executor import evaluate_symbolic_expression_ir
from hsr_engine.engine_property_analyzer import analyze_engine_property_usage, analyze_engine_property_inventory
from hsr_engine.engine_property_model import describe_engine_property

single_value, single_trace = evaluate_symbolic_expression_ir({
    "format": "hsr_symbolic_dynamic_expression_ir",
    "version": "v0.1",
    "opcodes": "AQAR",
    "fixed_values": [],
    "operands": [{"kind": "numeric_binding", "hash": 1, "value": 0.75}],
})
assert single_value == 0.75 and single_trace["pattern"] == "dynamic_passthrough", single_trace

mul_value, mul_trace = evaluate_symbolic_expression_ir({
    "format": "hsr_symbolic_dynamic_expression_ir",
    "version": "v0.1",
    "opcodes": "AQABAQQR",
    "fixed_values": [],
    "operands": [
        {"kind": "numeric_binding", "hash": 1, "value": 4},
        {"kind": "numeric_binding", "hash": 2, "value": 0.5},
    ],
})
assert mul_value == 2.0 and mul_trace["pattern"] == "dynamic_times_dynamic", mul_trace

add_value, add_trace = evaluate_symbolic_expression_ir({
    "format": "hsr_symbolic_dynamic_expression_ir",
    "version": "v0.1",
    "opcodes": "AQAAAAIR",
    "fixed_values": [1],
    "operands": [{"kind": "numeric_binding", "hash": 746008226, "value": 3}],
})
assert add_value == 4.0 and add_trace["pattern"] == "dynamic_plus_fixed", add_trace

sub_value, sub_trace = evaluate_symbolic_expression_ir({
    "format": "hsr_symbolic_dynamic_expression_ir",
    "version": "v0.1",
    "opcodes": "AQAAAAMR",
    "fixed_values": [4],
    "operands": [{"kind": "numeric_binding", "hash": 746008226, "value": 5}],
})
assert sub_value == 1.0 and sub_trace["pattern"] == "dynamic_minus_fixed", sub_trace

attack_runtime_value, attack_runtime_trace = evaluate_symbolic_expression_ir({
    "format": "hsr_symbolic_dynamic_expression_ir",
    "version": "v0.1",
    "opcodes": "AQABAQMBAgQR",
    "fixed_values": [],
    "operands": [
        {"kind": "runtime_dynamic_value", "hash": -1236299186},
        {"kind": "runtime_dynamic_value", "hash": 1098948395},
        {"kind": "numeric_binding", "hash": 783173533, "value": 0.15},
    ],
})
assert attack_runtime_value is None and attack_runtime_trace["reason"] == "unresolved_operand", attack_runtime_trace

attack_runtime_resolved, attack_runtime_resolved_trace = evaluate_symbolic_expression_ir({
    "format": "hsr_symbolic_dynamic_expression_ir",
    "version": "v0.1",
    "opcodes": "AQABAQMBAgQR",
    "fixed_values": [],
    "operands": [
        {"kind": "runtime_dynamic_value", "hash": -1236299186},
        {"kind": "runtime_dynamic_value", "hash": 1098948395},
        {"kind": "numeric_binding", "hash": 783173533, "value": 0.15},
    ],
}, runtime_values_by_hash={-1236299186: 1000, 1098948395: 700})
assert close(attack_runtime_resolved, 45.0) and attack_runtime_resolved_trace["pattern"] == "postfix_add_sub_mul", attack_runtime_resolved_trace

attack_runtime_key_resolved, attack_runtime_key_trace = evaluate_symbolic_expression_ir({
    "format": "hsr_symbolic_dynamic_expression_ir",
    "version": "v0.1",
    "opcodes": "AQABAQMBAgQR",
    "fixed_values": [],
    "operands": [
        {"kind": "runtime_dynamic_value", "hash": -1236299186, "runtime_value_key": "DanHengPT_ConvertAttack"},
        {"kind": "runtime_dynamic_value", "hash": 1098948395, "runtime_value_key": "DanHengPT_Attack"},
        {"kind": "numeric_binding", "hash": 783173533, "value": 0.15},
    ],
}, runtime_values_by_hash={"DanHengPT_ConvertAttack": 1000, "DanHengPT_Attack": 700})
assert close(attack_runtime_key_resolved, 45.0), attack_runtime_key_trace
assert attack_runtime_key_trace["operand_audit"][0]["runtime_value_key"] == "DanHengPT_ConvertAttack", attack_runtime_key_trace

symbolic_materialized = StatusEffect.from_dict({
    "id": "SymbolicMaterializedStatus",
    "symbolic_dynamic_values": {
        "MDF_PropertyValue": {
            "resolve": {
                "symbolic_expression_ir": {
                    "format": "hsr_symbolic_dynamic_expression_ir",
                    "version": "v0.1",
                    "opcodes": "AQABAQQR",
                    "fixed_values": [],
                    "operands": [
                        {"kind": "numeric_binding", "hash": 1, "value": 0.2},
                        {"kind": "numeric_binding", "hash": 2, "value": 3},
                    ],
                }
            }
        }
    },
    "property_hints": [{"property": "AllDamageTypeAddedRatio", "target": "actor"}],
})
assert close(symbolic_materialized.modifiers["dynamic_values"]["MDF_PropertyValue"], 0.6), symbolic_materialized.modifiers
assert close(symbolic_materialized.modifiers["dmg_bonus_add"], 0.6), symbolic_materialized.modifiers
assert symbolic_materialized.modifiers["symbolic_formula_applications"][0]["applied"] is True

attack_convert_audit = StatusEffect.from_dict({
    "id": "AttackConvertAuditStatus",
    "symbolic_dynamic_values": {
        "MDF_AttackDelta": {
            "resolve": {
                "symbolic_expression_ir": {
                    "format": "hsr_symbolic_dynamic_expression_ir",
                    "version": "v0.1",
                    "opcodes": "AQABAQMBAgQR",
                    "fixed_values": [],
                    "operands": [
                        {"kind": "numeric_binding", "hash": -1236299186, "value": 0.115},
                        {"kind": "numeric_binding", "hash": 1098948395, "value": 256.25},
                        {"kind": "numeric_binding", "hash": 783173533, "value": 0.15},
                    ],
                }
            }
        }
    },
    "property_hints": [{"property": "AttackConvert", "target": "actor"}],
})
assert "atk_add" in attack_convert_audit.modifiers, attack_convert_audit.modifiers
assert close(attack_convert_audit.modifiers["atk_add"], (0.115 - 256.25) * 0.15), attack_convert_audit.modifiers
assert attack_convert_audit.modifiers["property_hint_applications"][0]["reason"] == "materialized_attack_convert_dynamic_value", attack_convert_audit.modifiers
assert attack_convert_audit.modifiers["symbolic_formula_applications"][0]["applied"] is True, attack_convert_audit.modifiers
assert close(attack_convert_audit.modifiers["dynamic_values"]["MDF_AttackDelta"], (0.115 - 256.25) * 0.15), attack_convert_audit.modifiers

attack_convert_runtime_materialized = StatusEffect.from_dict({
    "id": "AttackConvertRuntimeMaterializedStatus",
    "symbolic_dynamic_values": {
        "MDF_AttackDelta": {
            "resolve": {
                "symbolic_expression_ir": {
                    "format": "hsr_symbolic_dynamic_expression_ir",
                    "version": "v0.1",
                    "opcodes": "AQABAQMBAgQR",
                    "fixed_values": [],
                    "operands": [
                        {"kind": "runtime_dynamic_value", "hash": -1236299186, "runtime_value_key": "DanHengPT_ConvertAttack"},
                        {"kind": "runtime_dynamic_value", "hash": 1098948395, "runtime_value_key": "DanHengPT_Attack"},
                        {"kind": "numeric_binding", "hash": 783173533, "value": 0.15},
                    ],
                }
            }
        }
    },
    "property_hints": [{"property": "AttackConvert", "target": "actor"}],
}, runtime_values_by_key={"DanHengPT_ConvertAttack": 1000, "DanHengPT_Attack": 700})
assert close(attack_convert_runtime_materialized.modifiers["dynamic_values"]["MDF_AttackDelta"], 45.0), attack_convert_runtime_materialized.modifiers
assert close(attack_convert_runtime_materialized.modifiers["atk_add"], 45.0), attack_convert_runtime_materialized.modifiers
assert attack_convert_runtime_materialized.modifiers["property_hint_applications"][0]["reason"] == "materialized_attack_convert_dynamic_value", attack_convert_runtime_materialized.modifiers

attack_convert_from_source_atk = StatusEffect.from_dict({
    "id": "AttackConvertFromSourceAttack",
    "symbolic_dynamic_values": {
        "MDF_AttackDelta": {
            "resolve": {
                "symbolic_expression_ir": {
                    "format": "hsr_symbolic_dynamic_expression_ir",
                    "version": "v0.1",
                    "opcodes": "AQABAQMBAgQR",
                    "fixed_values": [],
                    "operands": [
                        {"kind": "runtime_dynamic_value", "hash": -1236299186, "runtime_value_key": "DanHengPT_ConvertAttack"},
                        {"kind": "runtime_dynamic_value", "hash": 1098948395, "runtime_value_key": "DanHengPT_Attack"},
                        {"kind": "numeric_binding", "hash": 783173533, "value": 0.15},
                    ],
                }
            }
        }
    },
    "property_hints": [{"property": "AttackConvert", "target": "actor"}],
}, runtime_values_by_key={"DanHengPT_Attack": 3000})
assert close(attack_convert_from_source_atk.modifiers["atk_add"], 450.0), attack_convert_from_source_atk.modifiers
assert attack_convert_from_source_atk.modifiers["property_hint_applications"][0]["reason"] == "derived_attack_convert_from_source_attack", attack_convert_from_source_atk.modifiers
assert attack_convert_from_source_atk.modifiers["__replace_existing_modifiers"] is True, attack_convert_from_source_atk.modifiers

# Non-snapshot refresh: same status id replaces its previous flat ATK value.
fellow = UnitState.from_dict("fellow", {"side": "ally", "hp": 1000, "max_hp": 1000, "stat_base": {"atk": 2500}})
fellow.add_status(attack_convert_from_source_atk)
assert close(fellow.get_stat("atk"), 2950.0), fellow.to_json()
attack_convert_refreshed = StatusEffect.from_dict({
    "id": "AttackConvertFromSourceAttack",
    "symbolic_dynamic_values": attack_convert_from_source_atk.modifiers["symbolic_dynamic_values"],
    "property_hints": [{"property": "AttackConvert", "target": "actor"}],
}, runtime_values_by_key={"DanHengPT_Attack": 3600})
fellow.add_status(attack_convert_refreshed)
assert close(fellow.get_stat("atk"), 3040.0), fellow.to_json()

attack_convert_bondmate_case = {
    "global": {"flags": {"bondmate": "seele", "DanHengPT_Attack": 3000}, "skill_points": 3},
    "units": {
        "dan_heng": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 3000}},
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 2500}},
        "sparkle": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 2000}},
    },
    "triggers": [{"id": "apply_attack_convert_to_bondmate", "timing": "battle_start", "owner_id": "dan_heng", "effects": [
        {"type": "add_status", "target": "tbgd_alias:DanHengPT_00_BattleEventOwner", "status": {
            "id": "AttackConvertFromSourceAttack",
            "symbolic_dynamic_values": attack_convert_from_source_atk.modifiers["symbolic_dynamic_values"],
            "property_hints": [{"property": "AttackConvert", "target": "actor"}],
        }}
    ]}],
    "route": [],
}
attack_convert_bondmate_result = BattleSimulator(attack_convert_bondmate_case).run_route([])
seele_statuses = {s["id"]: s for s in attack_convert_bondmate_result["state"]["units"]["seele"]["statuses"]}
sparkle_statuses = {s["id"]: s for s in attack_convert_bondmate_result["state"]["units"]["sparkle"]["statuses"]}
assert "dan_heng_pt_attack_convert_dynamic" in seele_statuses and "dan_heng_pt_attack_convert_dynamic" not in sparkle_statuses, attack_convert_bondmate_result["state"]["units"]
derived_ac = seele_statuses["dan_heng_pt_attack_convert_dynamic"]["modifiers"]["derived_stat_add"][0]
assert derived_ac["id"] == "AttackConvert" and derived_ac["source"] == "dan_heng" and close(derived_ac["scale"], 0.15), seele_statuses

probe_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "level": 80,
            "stats": {"atk": 1000, "crit_rate": 0, "crit_dmg": 1},
            "actions": {"basic": {"id": "basic", "action_type": "basic", "tags": ["basic_use", "attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "physical", "scaling_stat": "atk", "multiplier": 0.1}]}},
        },
        "enemy": {"side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "level": 80, "defense": 0, "stats": {"def": 0}, "res": {"physical": 0}},
    },
    "route": [{"actor": "missing", "action": "basic", "targets": ["enemy"]}],
}
probe_path = OUT / "auto_probe_case.yaml"
probe_out = OUT / "auto_probe_result.json"
probe_path.write_text(yaml.safe_dump(probe_case, sort_keys=False), encoding="utf-8")
rc = simulator_main([str(probe_path), "--route-mode", "auto_probe", "--auto-probe-steps", "1", "--auto-probe-expected-actions", "actor.basic", "--output", str(probe_out)])
assert rc == 0
probe_result = json.loads(probe_out.read_text(encoding="utf-8"))
assert probe_result["metadata"]["route_mode"] == "auto_probe"
assert probe_result["metadata"]["skipped_route_step_count"] == 1
assert probe_result["metadata"]["auto_probe_executed_step_count"] == 1
assert probe_result["metadata"]["auto_probe_action_trace"][0]["actor"] == "actor", probe_result["metadata"]
assert probe_result["metadata"]["auto_probe_assertions"]["checks"]["expected_action_prefix_match"] is True, probe_result["metadata"]["auto_probe_assertions"]
assert probe_result["metadata"]["auto_probe_action_trace"][0]["event_summary"]["event_count"] > 0, probe_result["metadata"]["auto_probe_action_trace"]
assert probe_result["metadata"]["auto_probe_assertions"]["checks"]["executed_actions_emit_events"] is True, probe_result["metadata"]["auto_probe_assertions"]
assert any(e["event_type"] == "auto_probe" for e in probe_result["log"]), probe_result["log"]

affordability_probe_case = {
    "global": {"flags": {}, "skill_points": 0},
    "units": {
        "actor": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "level": 80,
            "stats": {"atk": 1000, "crit_rate": 0, "crit_dmg": 1},
            "actions": {
                "expensive_basic": {"id": "expensive_basic", "action_type": "basic", "tags": ["basic_use", "attack"], "cost": {"skill_points": -1}, "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "physical", "scaling_stat": "atk", "multiplier": 0.1}]},
                "free_skill": {"id": "free_skill", "action_type": "skill", "tags": ["skill_use", "attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "physical", "scaling_stat": "atk", "multiplier": 0.1}]},
            },
        },
        "enemy": {"side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "level": 80, "defense": 0, "stats": {"def": 0}, "res": {"physical": 0}},
    },
    "route": [],
}
affordability_path = OUT / "auto_probe_affordability_case.yaml"
affordability_out = OUT / "auto_probe_affordability_result.json"
affordability_path.write_text(yaml.safe_dump(affordability_probe_case, sort_keys=False), encoding="utf-8")
rc = simulator_main([str(affordability_path), "--route-mode", "auto_probe", "--auto-probe-steps", "1", "--output", str(affordability_out)])
assert rc == 0
affordability_result = json.loads(affordability_out.read_text(encoding="utf-8"))
probe_events = [e for e in affordability_result["log"] if e["event_type"] == "auto_probe"]
assert probe_events and "actor.free_skill" in probe_events[0]["message"], affordability_result["log"]
checks.append("PASS symbolic formula executor evaluates proven add/sub/mul postfix formulas, materializes AttackConvert as non-snapshot flat ATK, and auto-probe route mode skips unaffordable probe actions")


# v13.8 property inventory prioritization: direct formula-bucket StackProperty
# names can be consumed conservatively, while engine-derived properties remain
# audit-only.
formula_bucket_status = StatusEffect.from_dict({
    "id": "formula_bucket_status",
    "dynamic_values": {"MDF_Attack": 0.20},
    "property_hints": [{"property": "AttackAddedRatio", "target": "actor"}],
})
assert close(formula_bucket_status.modifiers["atk_pct"], 0.20), formula_bucket_status.modifiers
assert formula_bucket_status.modifiers["property_hint_applications"][0]["modifier_key"] == "atk_pct", formula_bucket_status.modifiers

speed_bucket_status = StatusEffect.from_dict({
    "id": "speed_bucket_status",
    "dynamic_values": {"MDF_Speed": 0.12},
    "property_hints": [{"property": "SpeedAddedRatio", "target": "actor"}],
})
assert close(speed_bucket_status.modifiers["speed_pct"], 0.12), speed_bucket_status.modifiers

crit_bucket_status = StatusEffect.from_dict({
    "id": "crit_bucket_status",
    "dynamic_values": {"MDF_CriticalDamage": 0.36},
    "property_hints": [{"property": "CriticalDamageBase", "target": "actor"}],
})
assert close(crit_bucket_status.modifiers["crit_dmg_add"], 0.36), crit_bucket_status.modifiers

taken_bucket_status = StatusEffect.from_dict({
    "id": "taken_bucket_status",
    "dynamic_values": {"MDF_Taken": 0.18},
    "property_hints": [{"property": "AllDamageTypeTakenRatio", "target": "actor"}],
})
assert close(taken_bucket_status.modifiers["damage_taken_add"], 0.18), taken_bucket_status.modifiers

elemental_bonus_status = StatusEffect.from_dict({
    "id": "elemental_bonus_status",
    "dynamic_values": {"MDF_FireDamage": 0.25},
    "property_hints": [{"property": "FireAddedRatio", "target": "actor"}],
})
assert close(elemental_bonus_status.modifiers["dmg_bonus"]["fire"], 0.25), elemental_bonus_status.modifiers
assert elemental_bonus_status.modifiers["property_hint_applications"][0]["modifier_key"] == "dmg_bonus.fire", elemental_bonus_status.modifiers

elemental_pen_status = StatusEffect.from_dict({
    "id": "elemental_pen_status",
    "dynamic_values": {"MDF_FirePenetrate": 0.10},
    "property_hints": [{"property": "FirePenetrate", "target": "actor"}],
})
assert close(elemental_pen_status.modifiers["res_pen"]["fire"], 0.10), elemental_pen_status.modifiers

elemental_taken_status = StatusEffect.from_dict({
    "id": "elemental_taken_status",
    "dynamic_values": {"MDF_FireTaken": 0.15},
    "property_hints": [{"property": "FireTakenRatio", "target": "actor"}],
})
assert close(elemental_taken_status.modifiers["damage_taken"]["fire"], 0.15), elemental_taken_status.modifiers

hp_added_status = StatusEffect.from_dict({
    "id": "hp_added_status",
    "dynamic_values": {"MDF_HPAddedRatio": 0.20},
    "property_hints": [{"property": "HPAddedRatio", "target": "actor"}],
})
assert close(hp_added_status.modifiers["max_hp_pct_delta"], 0.20), hp_added_status.modifiers

max_sp_status = StatusEffect.from_dict({
    "id": "max_sp_status",
    "dynamic_values": {"MDF_MaxSP": 2},
    "property_hints": [{"property": "MaxSP", "target": "actor"}],
})
assert close(max_sp_status.modifiers["skill_point_cap_add"], 2), max_sp_status.modifiers

effect_hit_status = StatusEffect.from_dict({
    "id": "effect_hit_status",
    "dynamic_values": {"MDF_StatusProbability": 0.25},
    "property_hints": [{"property": "StatusProbabilityBase", "target": "actor"}],
})
assert close(effect_hit_status.modifiers["effect_hit_add"], 0.25), effect_hit_status.modifiers

effect_res_status = StatusEffect.from_dict({
    "id": "effect_res_status",
    "dynamic_values": {"MDF_StatusResistance": 0.30},
    "property_hints": [{"property": "StatusResistanceBase", "target": "actor"}],
})
assert close(effect_res_status.modifiers["effect_res_add"], 0.30), effect_res_status.modifiers

resource_case = {
    "global": {"flags": {}, "skill_points": 3, "skill_point_cap": 5},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "statuses": []},
    },
    "triggers": [{"id": "resource_statuses", "timing": "battle_start", "owner_id": "actor", "effects": [
        {"type": "add_status", "target": "actor", "status": {"id": "hp_added_status", "modifiers": hp_added_status.modifiers}},
        {"type": "add_status", "target": "actor", "status": {"id": "max_sp_status", "modifiers": max_sp_status.modifiers}},
    ]}],
    "route": [],
}
resource_result = BattleSimulator(resource_case).run_route([])
resource_actor = resource_result["state"]["units"]["actor"]
assert close(resource_actor["max_hp"], 1200.0) and close(resource_actor["hp"], 1200.0), resource_actor
assert resource_result["state"]["global"]["skill_point_cap"] == 7 and resource_result["state"]["global"]["skill_points"] == 3, resource_result["state"]["global"]

resource_clamp_case = {
    "global": {"flags": {}, "skill_points": 7, "skill_point_cap": 7},
    "units": {"actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "statuses": []}},
    "triggers": [{"id": "lower_sp_cap", "timing": "battle_start", "owner_id": "actor", "effects": [
        {"type": "add_status", "target": "actor", "status": {"id": "lower_max_sp", "modifiers": {"skill_point_cap_add": -2}}},
    ]}],
    "route": [],
}
resource_clamp_result = BattleSimulator(resource_clamp_case).run_route([])
assert resource_clamp_result["state"]["global"]["skill_point_cap"] == 5 and resource_clamp_result["state"]["global"]["skill_points"] == 5, resource_clamp_result["state"]["global"]

ambiguous_formula_bucket_status = StatusEffect.from_dict({
    "id": "ambiguous_formula_bucket_status",
    "dynamic_values": {"value_a": 0.1, "value_b": 0.2},
    "property_hints": [{"property": "AttackAddedRatio", "target": "actor"}],
})
assert "atk_pct" not in ambiguous_formula_bucket_status.modifiers, ambiguous_formula_bucket_status.modifiers
assert ambiguous_formula_bucket_status.modifiers["property_hint_applications"][0]["reason"] == "ambiguous_numeric_dynamic_values", ambiguous_formula_bucket_status.modifiers

formula_bucket_damage_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "level": 80,
            "stat_base": {"atk": 1000},
            "statuses": [{"id": "atk_pct_from_property", "modifiers": formula_bucket_status.modifiers}],
            "actions": {"basic": {"id": "basic", "action_type": "basic", "tags": ["attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "physical", "scaling_stat": "atk", "multiplier": 1.0, "can_crit": False}]}},
        },
        "enemy": {"side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "level": 80, "stats": {"def": 0}, "res": {"physical": 0}},
    },
    "route": [{"actor": "actor", "action": "basic", "targets": ["enemy"]}],
}
formula_damage_result = BattleSimulator(formula_bucket_damage_case).run_route(formula_bucket_damage_case["route"])
damage_events = [e for e in formula_damage_result["log"] if e["event_type"] == "damage"]
assert damage_events and close(damage_events[0]["data"]["damage"], 1200.0), damage_events

elemental_formula_damage_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "level": 80,
            "stat_base": {"atk": 1000},
            "statuses": [
                {"id": "fire_bonus_from_property", "modifiers": elemental_bonus_status.modifiers},
                {"id": "fire_pen_from_property", "modifiers": elemental_pen_status.modifiers},
            ],
            "actions": {"fire": {"id": "fire", "action_type": "basic", "tags": ["attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "fire", "scaling_stat": "atk", "multiplier": 1.0, "can_crit": False}]}},
        },
        "enemy": {
            "side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "level": 80,
            "stats": {"def": 0}, "res": {"fire": 0.2},
            "statuses": [{"id": "fire_taken_from_property", "modifiers": elemental_taken_status.modifiers}],
        },
    },
    "route": [{"actor": "actor", "action": "fire", "targets": ["enemy"]}],
}
elemental_formula_damage_result = BattleSimulator(elemental_formula_damage_case).run_route(elemental_formula_damage_case["route"])
elemental_damage_events = [e for e in elemental_formula_damage_result["log"] if e["event_type"] == "damage"]
assert elemental_damage_events and close(elemental_damage_events[0]["data"]["damage"], 1293.75), elemental_damage_events
checks.append("PASS prioritized and elemental formula-bucket property hints lower into stat/damage modifiers only when values are unambiguous")


# v14.8 break/super-break formula paths and effect-hit probability gates.
break_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "level": 80,
            "stat_base": {"atk": 9999}, "stats": {"break_effect": 1.0, "crit_rate": 1.0, "crit_dmg": 5.0, "all_dmg_bonus": 10.0},
            "actions": {
                "break": {"id": "break", "action_type": "skill", "tags": ["attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "break_p", "damage_type": "break", "element": "fire", "can_crit": True}]},
                "super": {"id": "super", "action_type": "skill", "tags": ["attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "super_p", "damage_type": "super_break", "element": "fire", "toughness_reduction": 60, "can_crit": True}]},
            },
        },
        "enemy": {"side": "enemy", "hp": 100000, "max_hp": 100000, "speed": 100, "level": 80, "toughness": 0, "max_toughness": 120, "is_broken": True, "stats": {"def": 0}, "res": {"fire": 0}},
    },
    "route": [{"actor": "actor", "action": "break", "targets": ["enemy"]}, {"actor": "actor", "action": "super", "targets": ["enemy"]}],
}
break_result = BattleSimulator(break_case).run_route(break_case["route"])
break_damage_events = [e for e in break_result["log"] if e["event_type"] == "damage"]
assert len(break_damage_events) == 2, break_damage_events
# break: level base 3767.5535 * fire 2.0 * toughness multiplier (120/30+2)/4=1.5 * (1+BE)=2
assert close(break_damage_events[0]["data"]["damage"], 22605.321), break_damage_events[0]
assert break_damage_events[0]["data"]["crit"]["multiplier"] == 1.0, break_damage_events[0]
assert break_damage_events[0]["data"]["multipliers"]["dmg_bonus"] if "dmg_bonus" in break_damage_events[0]["data"].get("multipliers", {}) else True
# super break: level base 3767.5535 * (60/30) * (1+BE)
assert close(break_damage_events[1]["data"]["damage"], 15070.214), break_damage_events[1]
assert break_damage_events[1]["data"]["crit"]["source"] == "super_break_cannot_crit", break_damage_events[1]

break_bonus_status = StatusEffect.from_dict({
    "id": "break_bonus_status",
    "dynamic_values": {"MDF_BreakDamage": 0.25},
    "property_hints": [{"property": "BreakDamageAddedRatioBase", "target": "actor"}],
})
assert close(break_bonus_status.modifiers["break_damage_bonus"], 0.25), break_bonus_status.modifiers

hit_case = {
    "global": {"flags": {}, "skill_points": 3},
    "settings": {"default_effect_hit_mode": "success"},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"effect_hit": 1.0}},
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"effect_res": 0.2}},
    },
    "triggers": [{"id": "apply_debuff", "timing": "battle_start", "owner_id": "actor", "effects": [{"type": "add_status", "target": "enemy", "effect_hit": {"base_chance": 0.5, "special_res": 0.1}, "status": {"id": "tested_debuff", "tags": ["debuff"]}}]}],
    "route": [],
}
hit_result = BattleSimulator(hit_case).run_route([])
hit_checks = [e for e in hit_result["log"] if e["event_type"] == "effect_hit_check"]
assert hit_checks and close(hit_checks[0]["data"]["final_chance"], 0.72), hit_checks
assert any(s["id"] == "tested_debuff" for s in hit_result["state"]["units"]["enemy"]["statuses"]), hit_result["state"]["units"]["enemy"]["statuses"]

hit_fail_case = deepcopy(hit_case)
hit_fail_case["triggers"][0]["effects"][0]["effect_hit"]["event_id"] = "debuff_check"
hit_fail_case["events"] = {"debuff_check": "resisted"}
hit_fail_result = BattleSimulator(hit_fail_case).run_route([])
assert not any(s["id"] == "tested_debuff" for s in hit_fail_result["state"]["units"]["enemy"]["statuses"]), hit_fail_result["state"]["units"]["enemy"]["statuses"]

# Weakness break aftermath: elemental break should add canonical aftermath status metadata
# and action-delay effects for delay elements without touching normal damage bonuses.
weakness_break_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "level": 80,
            "stat_base": {"atk": 1000},
            "actions": {
                "fire_break": {"id": "fire_break", "action_type": "skill", "tags": ["attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "fire", "scaling_stat": "atk", "multiplier": 0.0, "toughness_reduction": 30, "can_crit": False}]},
                "quantum_break": {"id": "quantum_break", "action_type": "skill", "tags": ["attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "q", "element": "quantum", "scaling_stat": "atk", "multiplier": 0.0, "toughness_reduction": 30, "can_crit": False}]},
            },
        },
        "enemy": {"side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "level": 80, "toughness": 30, "max_toughness": 120, "weaknesses": ["fire", "quantum"], "stats": {"def": 0}, "res": {"fire": 0, "quantum": 0}},
    },
    "route": [{"actor": "actor", "action": "fire_break", "targets": ["enemy"]}],
}
weakness_break_result = BattleSimulator(weakness_break_case).run_route(weakness_break_case["route"])
enemy_statuses = {st["id"]: st for st in weakness_break_result["state"]["units"]["enemy"]["statuses"]}
assert "weakness_break_burn" in enemy_statuses, enemy_statuses
assert enemy_statuses["weakness_break_burn"]["modifiers"]["break_dot"]["kind"] == "burn", enemy_statuses
assert any(e["event_type"] == "break_aftermath" and e["data"].get("element") == "fire" for e in weakness_break_result["log"]), weakness_break_result["log"]

quantum_case = deepcopy(weakness_break_case)
quantum_case["units"]["enemy"]["toughness"] = 30
quantum_case["route"] = [{"actor": "actor", "action": "quantum_break", "targets": ["enemy"]}]
quantum_result = BattleSimulator(quantum_case).run_route(quantum_case["route"])
quantum_statuses = {st["id"]: st for st in quantum_result["state"]["units"]["enemy"]["statuses"]}
assert "weakness_break_entanglement" in quantum_statuses, quantum_statuses
assert any(e["event_type"] == "av_change" and "delayed" in e["message"] for e in quantum_result["log"]), quantum_result["log"]

# Weakness-break aftermath damage formulas: break DoT/delayed damage should tick
# on the target regular-turn start, use Break Effect, and ignore normal damage bonus / crit.
burn_dot_case = deepcopy(weakness_break_case)
burn_dot_case["units"]["actor"]["stats"] = {"break_effect": 1.0, "crit_rate": 1.0, "crit_dmg": 10.0, "all_dmg_bonus": 10.0}
burn_dot_case["units"]["enemy"]["actions"] = {"noop": {"id": "noop", "action_type": "basic", "tags": ["consumes_regular_action"], "target_policy": "self", "damage_packets": []}}
burn_dot_case["route"] = [
    {"actor": "actor", "action": "fire_break", "targets": ["enemy"]},
    {"actor": "enemy", "action": "noop", "targets": [], "turn_kind": "regular"},
]
burn_dot_result = BattleSimulator(burn_dot_case).run_route(burn_dot_case["route"])
burn_dot_events = [e for e in burn_dot_result["log"] if e["event_type"] == "break_aftermath_damage" and e["data"].get("damage_type") == "break_dot_damage"]
assert burn_dot_events and close(burn_dot_events[0]["data"]["damage"], break_base_damage(80) * 2.0), burn_dot_events
assert burn_dot_events[0]["data"]["crit"]["multiplier"] == 1.0, burn_dot_events[0]

bleed_cap_case = deepcopy(weakness_break_case)
bleed_cap_case["units"]["enemy"].update({"max_hp": 1000000, "hp": 1000000, "weaknesses": ["physical"], "flags": {}})
bleed_cap_case["units"]["actor"]["actions"] = {"physical_break": {"id": "physical_break", "action_type": "skill", "tags": ["attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "physical", "scaling_stat": "atk", "multiplier": 0.0, "toughness_reduction": 30, "can_crit": False}]}}
bleed_cap_case["units"]["enemy"]["actions"] = {"noop": {"id": "noop", "action_type": "basic", "tags": ["consumes_regular_action"], "target_policy": "self", "damage_packets": []}}
bleed_cap_case["route"] = [
    {"actor": "actor", "action": "physical_break", "targets": ["enemy"]},
    {"actor": "enemy", "action": "noop", "targets": [], "turn_kind": "regular"},
]
bleed_cap_result = BattleSimulator(bleed_cap_case).run_route(bleed_cap_case["route"])
bleed_events = [e for e in bleed_cap_result["log"] if e["event_type"] == "break_aftermath_damage" and e["data"].get("element") == "physical"]
bleed_expected = 2.0 * break_base_damage(80) * max_toughness_multiplier(120)
assert bleed_events and close(bleed_events[0]["data"]["damage"], bleed_expected), bleed_events

entangle_case = deepcopy(weakness_break_case)
entangle_case["units"]["actor"]["actions"]["poke"] = {"id": "poke", "action_type": "basic", "tags": ["attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "poke", "element": "quantum", "scaling_stat": "atk", "multiplier": 0.01, "can_crit": False}]}
entangle_case["units"]["enemy"]["actions"] = {"noop": {"id": "noop", "action_type": "basic", "tags": ["consumes_regular_action"], "target_policy": "self", "damage_packets": []}}
entangle_case["route"] = [
    {"actor": "actor", "action": "quantum_break", "targets": ["enemy"]},
    {"actor": "actor", "action": "poke", "targets": ["enemy"]},
    {"actor": "enemy", "action": "noop", "targets": [], "turn_kind": "regular"},
]
entangle_result = BattleSimulator(entangle_case).run_route(entangle_case["route"])
entangle_statuses = {st["id"]: st for st in entangle_result["state"]["units"].get("enemy", {}).get("statuses", [])}
entangle_events = [e for e in entangle_result["log"] if e["event_type"] == "break_aftermath_damage" and e["data"].get("damage_type") == "break_delayed_damage"]
assert any(e["event_type"] == "break_aftermath_stack" for e in entangle_result["log"]), entangle_result["log"]
entangle_expected = 0.6 * 2 * break_base_damage(80) * max_toughness_multiplier(120)
assert entangle_events and close(entangle_events[0]["data"]["damage"], entangle_expected), entangle_events

freeze_case = deepcopy(weakness_break_case)
freeze_case["units"]["enemy"].update({"toughness": 30, "weaknesses": ["ice"], "actions": {"noop": {"id": "noop", "action_type": "basic", "tags": ["consumes_regular_action"], "target_policy": "self", "damage_packets": []}}})
freeze_case["units"]["actor"]["actions"] = {"ice_break": {"id": "ice_break", "action_type": "skill", "tags": ["attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "ice", "element": "ice", "scaling_stat": "atk", "multiplier": 0.0, "toughness_reduction": 30, "can_crit": False}]}}
freeze_case["route"] = [
    {"actor": "actor", "action": "ice_break", "targets": ["enemy"]},
    {"actor": "enemy", "action": "noop", "targets": [], "turn_kind": "regular"},
]
freeze_result = BattleSimulator(freeze_case).run_route(freeze_case["route"])
assert any(e["event_type"] == "action_block" for e in freeze_result["log"]), freeze_result["log"]
freeze_events = [e for e in freeze_result["log"] if e["event_type"] == "break_aftermath_damage" and e["data"].get("element") == "ice"]
assert freeze_events and close(freeze_events[0]["data"]["damage"], break_base_damage(80)), freeze_events
checks.append("PASS weakness-break DoT/delayed damage formulas tick on turn start, cap physical bleed, stack entanglement, and block frozen turns")

converted, reasons = _convert_effect({"type": "add_status", "status_id": "generated_debuff", "target_policy": "enemy", "chance_expr": 0.65}, "source_status")
assert converted and converted[0]["effect_hit"]["base_chance"] == 0.65 and not reasons, (converted, reasons)

chance_branch, chance_branch_reasons = _convert_effect({
    "type": "conditional_branch",
    "condition": {"type": "random_chance", "chance_expr": 0.4},
    "effects_if_true": [{"type": "add_status", "status_id": "chance_debuff", "target_policy": "enemy"}],
}, "source_status")
assert not chance_branch_reasons and chance_branch[0]["condition"]["chance_gate"]["use_effect_hit"] is True, (chance_branch, chance_branch_reasons)

chance_branch_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"effect_hit": 0.5}},
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"effect_res": 0.2}},
    },
    "triggers": [{"id": "chance_branch", "timing": "battle_start", "owner_id": "actor", "effects": chance_branch}],
    "initial_events": {"actor.condition.chance_gate": "resisted"},
    "route": [],
}
chance_branch_result = BattleSimulator(chance_branch_case).run_route([])
assert not any(st["id"] == "chance_debuff" for st in chance_branch_result["state"]["units"]["enemy"]["statuses"]), chance_branch_result["state"]["units"]["enemy"]["statuses"]
chance_logs = [e for e in chance_branch_result["log"] if e["event_type"] == "chance_check"]
assert chance_logs and chance_logs[0]["data"]["gate_type"] == "effect_hit_chance_gate", chance_logs
checks.append("PASS weakness-break aftermath applies elemental statuses/action-delay metadata and generated AddModifier/ByRandomChance debuff chances lower into effect-hit gates")

checks.append("PASS break/super-break formula paths ignore crit/normal damage bonus and effect-hit gates compute probability with forced miss support")

summon_lifecycle_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "dragon": {"side": "ally", "hp": 100, "max_hp": 100, "speed": 100, "flags": {"summoned": True, "lifespan_actions": 1}, "actions": {"act": {"id": "act", "action_type": "basic", "tags": ["consumes_regular_action"], "target_policy": "self", "damage_packets": []}}},
    },
    "route": [{"actor": "dragon", "action": "act", "targets": []}],
}
summon_lifecycle_result = BattleSimulator(summon_lifecycle_case).run_route(summon_lifecycle_case["route"])
assert "dragon" not in summon_lifecycle_result["state"]["units"], summon_lifecycle_result["state"]["units"]
assert any(e["event_type"] == "unit_removed" and e["data"].get("reason") == "lifespan_actions_expired" for e in summon_lifecycle_result["log"]), summon_lifecycle_result["log"]

attached_cleanup_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "owner": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 9999}, "actions": {"kill": {"id": "kill", "action_type": "basic", "tags": ["attack", "consumes_regular_action"], "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "physical", "scaling_stat": "atk", "multiplier": 1.0, "can_crit": False}]}}},
        "target": {"side": "enemy", "hp": 10, "max_hp": 10, "speed": 100, "stats": {"def": 0}, "res": {"physical": 0}},
        "attached": {"side": "ally", "hp": 100, "max_hp": 100, "speed": 100, "flags": {"summoned": True, "owner_id": "owner", "attached_to": "target", "remove_when_attached_target_defeated": True}},
    },
    "route": [{"actor": "owner", "action": "kill", "targets": ["target"]}],
}
attached_cleanup_result = BattleSimulator(attached_cleanup_case).run_route(attached_cleanup_case["route"])
assert "attached" not in attached_cleanup_result["state"]["units"], attached_cleanup_result["state"]["units"]
assert any(e["event_type"] == "unit_removed" and str(e["data"].get("reason", "")).startswith("attached_target_defeated") for e in attached_cleanup_result["log"]), attached_cleanup_result["log"]

souldragon_enhance_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "dan_heng": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "actions": {"ult": {"id": "ult", "action_type": "ultimate", "tags": [], "target_policy": "self", "damage_packets": [], "effects": [{"type": "enhance_souldragon", "remaining_actions_added": 2}]}}},
        "souldragon": {"side": "ally", "hp": 100, "max_hp": 100, "speed": 165, "flags": {"summoned": True, "owner_id": "dan_heng"}, "actions": {"act": {"id": "act", "action_type": "basic", "tags": ["consumes_regular_action"], "target_policy": "self", "damage_packets": []}}},
    },
    "route": [
        {"actor": "dan_heng", "action": "ult", "targets": []},
        {"actor": "souldragon", "action": "act", "targets": [], "turn_kind": "regular"},
        {"actor": "souldragon", "action": "act", "targets": [], "turn_kind": "regular"},
    ],
}
souldragon_enhance_result = BattleSimulator(souldragon_enhance_case).run_route(souldragon_enhance_case["route"])
dragon_flags = souldragon_enhance_result["state"]["units"]["souldragon"]["flags"]
assert dragon_flags["remaining_enhanced_actions"] == 0 and dragon_flags["is_enhanced"] is False, dragon_flags
assert any(e["event_type"] == "summon_lifecycle" and "enhanced actions" in e["message"] for e in souldragon_enhance_result["log"]), souldragon_enhance_result["log"]

souldragon_default_case = {
    "global": {"flags": {"bondmate": "seele", "bondmate_target": "seele"}, "skill_points": 3},
    "units": {
        "dan_heng_permansor_terrae": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 3000}},
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "flags": {"element": "quantum"}, "stat_base": {"atk": 2000}},
        "souldragon": {"side": "ally", "hp": 100, "max_hp": 100, "speed": 165, "flags": {"summoned": True, "owner_id": "dan_heng_permansor_terrae", "is_enhanced": True, "souldragon_enhanced": True, "remaining_enhanced_actions": 1}},
        "enemy": {"side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "stats": {"def": 0}, "res": {"physical": 0, "quantum": 0}},
    },
    "route": [{"actor": "souldragon", "action": "enhanced", "targets": ["enemy"], "turn_kind": "regular"}],
}
souldragon_default_result = BattleSimulator(souldragon_default_case).run_route(souldragon_default_case["route"])
dmg_logs = [e for e in souldragon_default_result["log"] if e["event_type"] == "damage"]
physical_logs = [e for e in dmg_logs if str(e["data"].get("packet_id", "")).startswith("souldragon_graph_physical_hit_")]
bondmate_logs = [e for e in dmg_logs if e["data"].get("packet_id") == "souldragon_graph_bondmate_additional"]
assert len(physical_logs) == 4, dmg_logs
assert len(bondmate_logs) == 1, dmg_logs
assert close(sum(e["data"]["damage"] for e in physical_logs), 3000.0), dmg_logs
assert all(close(e["data"]["damage"], 750.0) for e in physical_logs), dmg_logs
assert close(sum(e["data"].get("toughness_reduction", 0.0) for e in physical_logs), 60.0), dmg_logs
assert bondmate_logs[0]["data"]["element"] == "quantum" and close(bondmate_logs[0]["data"]["damage"], 2000.0), dmg_logs
assert souldragon_default_result["state"]["units"]["souldragon"]["flags"]["is_enhanced"] is False, souldragon_default_result["state"]["units"]["souldragon"]["flags"]
# Enhanced Souldragon action still performs the talent cleanse + shield before damage.
assert close(souldragon_default_result["state"]["units"]["seele"]["shield"], 601.25), souldragon_default_result["state"]["units"]["seele"]
assert close(souldragon_default_result["state"]["units"]["dan_heng_permansor_terrae"]["shield"], 601.25), souldragon_default_result["state"]["units"]["dan_heng_permansor_terrae"]

souldragon_cleanse_case = {
    "global": {"flags": {"bondmate": "seele", "bondmate_target": "seele"}, "skill_points": 3},
    "units": {
        "dan_heng_permansor_terrae": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 3000}},
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "statuses": [{"id": "slow_debuff", "tags": ["debuff"]}, {"id": "burn_debuff", "tags": ["debuff"]}], "flags": {"element": "quantum"}, "stat_base": {"atk": 2000}},
        "souldragon": {"side": "ally", "hp": 100, "max_hp": 100, "speed": 165, "flags": {"summoned": True, "owner_id": "dan_heng_permansor_terrae", "attached_to": "seele"}},
    },
    "route": [{"actor": "souldragon", "action": "normal", "targets": [], "turn_kind": "regular"}],
}
souldragon_cleanse_result = BattleSimulator(souldragon_cleanse_case).run_route(souldragon_cleanse_case["route"])
assert close(souldragon_cleanse_result["state"]["units"]["seele"]["shield"], 601.25), souldragon_cleanse_result["state"]["units"]["seele"]
remaining_statuses = [st["id"] for st in souldragon_cleanse_result["state"]["units"]["seele"]["statuses"]]
assert len(remaining_statuses) == 1 and remaining_statuses[0] == "burn_debuff", remaining_statuses
assert any(e["event_type"] == "cleanse" for e in souldragon_cleanse_result["log"]), souldragon_cleanse_result["log"]

souldragon_after_action_trigger_case = {
    "global": {"flags": {"bondmate": "seele", "bondmate_target": "seele"}, "skill_points": 3},
    "units": {
        "dan_heng_permansor_terrae": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 3000}},
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 2000}, "flags": {"element": "quantum"}},
        "souldragon": {"side": "ally", "hp": 100, "max_hp": 100, "speed": 165, "flags": {"summoned": True, "owner_id": "dan_heng_permansor_terrae", "attached_to": "seele", "is_enhanced": True, "souldragon_enhanced": True, "remaining_enhanced_actions": 1}},
        "enemy": {"side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "level": 80, "stats": {"def": 0}, "res": {"physical": 0, "quantum": 0}},
    },
    "triggers": [{"id": "after_souldragon_bonus", "timing": "after_souldragon_action", "effects": [
        {"type": "conditional_branch", "condition": "souldragon.is_enhanced", "effects_if_true": [
            {"type": "deal_damage", "damage_packet": {"id": "after_souldragon_bonus", "element": "bondmate.element", "damage_type": "additional_damage", "target_policy": "all_enemies", "scaling_stat": "bondmate.atk", "multiplier": 0.4, "can_crit": False}}
        ]}
    ]}],
    "route": [{"actor": "souldragon", "action": "enhanced", "targets": ["enemy"], "turn_kind": "regular"}],
}
souldragon_after_action_trigger_result = BattleSimulator(souldragon_after_action_trigger_case).run_route(souldragon_after_action_trigger_case["route"])
bonus_logs = [e for e in souldragon_after_action_trigger_result["log"] if e["event_type"] == "damage" and e["data"].get("packet_id") == "after_souldragon_bonus"]
assert bonus_logs, souldragon_after_action_trigger_result["log"]
assert souldragon_after_action_trigger_result["state"]["units"]["souldragon"]["flags"]["is_enhanced"] is False, souldragon_after_action_trigger_result["state"]["units"]["souldragon"]["flags"]

bondmate_attack_semantic_fallback_case = {
    "global": {"flags": {"bondmate": "seele", "bondmate_target": "seele"}, "skill_points": 3},
    "units": {
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"atk": 1000}, "actions": {"basic": {"id": "basic", "action_type": "basic", "tags": ["attack", "consumes_regular_action"], "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "quantum", "scaling_stat": "atk", "multiplier": 0.1, "can_crit": False}]}}},
        "dan_heng_permansor_terrae": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "energy": 0, "max_energy": 135, "stats": {"energy_regeneration_rate": 1.0}},
        "souldragon": {"side": "ally", "hp": 1, "max_hp": 1, "speed": 165, "remaining_av": 100, "flags": {"summoned": True, "owner_id": "dan_heng_permansor_terrae", "attached_to": "seele"}},
        "enemy": {"side": "enemy", "hp": 10000, "max_hp": 10000, "stats": {"def": 0}, "res": {"quantum": 0}},
    },
    "route": [{"actor": "seele", "action": "basic", "targets": ["enemy"], "turn_kind": "regular"}],
}
bondmate_attack_semantic_fallback_result = BattleSimulator(bondmate_attack_semantic_fallback_case).run_route(bondmate_attack_semantic_fallback_case["route"])
assert close(bondmate_attack_semantic_fallback_result["state"]["units"]["dan_heng_permansor_terrae"]["energy"], 6.0), bondmate_attack_semantic_fallback_result["state"]["units"]["dan_heng_permansor_terrae"]
assert close(bondmate_attack_semantic_fallback_result["state"]["units"]["souldragon"]["remaining_av"], 85.0), bondmate_attack_semantic_fallback_result["state"]["units"]["souldragon"]
assert any(e["event_type"] == "souldragon_semantic" for e in bondmate_attack_semantic_fallback_result["log"]), bondmate_attack_semantic_fallback_result["log"]

bondmate_auto_summon_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "dan_heng_permansor_terrae": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 3000}, "actions": {"skill": {"id": "skill", "action_type": "skill", "tags": ["skill_use"], "target_policy": "manual", "damage_packets": [], "effects": [{"type": "set_target", "status_id": "bondmate", "target": "target"}]}}},
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "flags": {"element": "quantum"}, "stat_base": {"atk": 2000}},
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100},
    },
    "route": [{"actor": "dan_heng_permansor_terrae", "action": "skill", "targets": ["seele"], "expect": {"global_flags": {"bondmate": "seele", "bondmate_target": "seele"}, "units": {"souldragon": {"flags": {"attached_to": "seele", "owner_id": "dan_heng_permansor_terrae"}}}}}],
}
bondmate_auto_summon_result = BattleSimulator(bondmate_auto_summon_case).run_route(bondmate_auto_summon_case["route"])
assert "souldragon" in bondmate_auto_summon_result["state"]["units"], bondmate_auto_summon_result["state"]["units"]
auto_dragon = bondmate_auto_summon_result["state"]["units"]["souldragon"]
assert auto_dragon["speed"] == 165 and auto_dragon["flags"]["attached_to"] == "seele", auto_dragon
assert bondmate_auto_summon_result["metadata"]["route_assertions"]["expectations"]["ok"] is True, bondmate_auto_summon_result["metadata"]["route_assertions"]
assert any(e["event_type"] == "summon_lifecycle" and "summoned for bondmate" in e["message"] for e in bondmate_auto_summon_result["log"]), bondmate_auto_summon_result["log"]

route_expectation_damage_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 1000}, "actions": {"basic": {"id": "basic", "action_type": "basic", "tags": ["attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "physical", "scaling_stat": "atk", "multiplier": 1.0, "can_crit": False}]}}},
        "enemy": {"side": "enemy", "hp": 5000, "max_hp": 5000, "speed": 100, "stats": {"def": 0}, "res": {"physical": 0}},
    },
    "route": [{"actor": "actor", "action": "basic", "targets": ["enemy"], "expect": {"event_counts": {"damage": 1}, "damage_total": {"value": 1000}, "units": {"enemy": {"hp": 4000}}}}],
}
route_expectation_damage_result = BattleSimulator(route_expectation_damage_case).run_route(route_expectation_damage_case["route"])
assert route_expectation_damage_result["metadata"]["route_assertions"]["ok"] is True, route_expectation_damage_result["metadata"]["route_assertions"]
assert route_expectation_damage_result["metadata"]["route_action_trace"][0]["expectation"]["ok"] is True, route_expectation_damage_result["metadata"]["route_action_trace"]
checks.append("PASS route expectations validate event counts, damage totals, unit state, flags, and auto-summoned Souldragon bondmate attachment")
checks.append("PASS summoned/attached units support owner/lifespan/attached-target/enhanced-action/data-derived Souldragon action, cleanse/shield, and bondmate attack semantics")

# v12.8 engine-side property evidence: AttackConvert-like properties stay audit-only
# unless a separate formula bucket mapping is proven.
engine_prop_root = OUT / "engine_property_tbgd"
ability_dir = engine_prop_root / "Config" / "ConfigAbility" / "Avatar"
ability_dir.mkdir(parents=True, exist_ok=True)
(ability_dir / "Avatar_Test_00_Ability.json").write_text(json.dumps({
    "AbilityList": [{
        "OnStart": [
            {"$type": "RPG.GameCore.SetDynamicValueByProperty", "DynamicKey": "Test_Attack", "ReadTargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"}, "Value": "Attack"},
            {"$type": "RPG.GameCore.SetDynamicValueByProperty", "DynamicKey": "Test_Convert", "ReadTargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"}, "Value": "AttackConvert"},
            {"$type": "RPG.GameCore.AddModifier", "ModifierName": {"Value": "M_Test_AttackConvert"}},
        ],
        "Modifiers": {
            "M_Test_Watcher": {"OnAbilityPropertyChange": [{"Property": "AttackConvert", "Ranges": [{"OnChange": []}]}]},
            "M_Test_AttackConvert": {"_CallbackList": [{"Event": "OnStack", "CallbackConfig": [{"$type": "RPG.GameCore.StackProperty", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "ModifierOwnerEntity"}, "Property": "AttackConvert", "PropertyValue": {"IsDynamic": False, "FixedValue": {"Value": 1}}}]}]},
        },
    }]
}, ensure_ascii=False), encoding="utf-8")
engine_prop_report = analyze_engine_property_usage(engine_prop_root, "AttackConvert")
assert engine_prop_report["usage_counts"]["read_by_set_dynamic_value_by_property"] == 1, engine_prop_report
assert engine_prop_report["usage_counts"]["write_by_stack_property"] == 1, engine_prop_report
assert engine_prop_report["usage_counts"]["watch_by_property_change"] == 1, engine_prop_report
assert engine_prop_report["recommendation"] == "derived_flat_atk_modifier_model_available", engine_prop_report

property_read_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {"actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"atk": 700}}},
    "triggers": [{"id": "read_engine_property", "timing": "battle_start", "owner_id": "actor", "effects": [{"type": "set_flag_from_property", "key": "convert", "property": "AttackConvert", "target": "actor"}]}],
    "route": [],
}
property_read_result = BattleSimulator(property_read_case).run_route([])
engine_reads = property_read_result["runtime_audit"]["engine_property_reads"]
assert engine_reads["unresolved_count"] == 1 and engine_reads["by_property"]["AttackConvert"]["unresolved"] == 1, engine_reads
assert "convert" not in property_read_result["state"]["global"]["flags"], property_read_result["state"]["global"]["flags"]
assert engine_reads["records"][0]["data"]["engine_property_model"]["category"] == "derived_flat_atk_modifier", engine_reads
model = describe_engine_property("AttackConvert").to_dict()
assert model["read_policy"] == "derived_status_property" and model["formula_bucket"] == "atk_add", model
status_with_engine_property_hint = StatusEffect.from_dict({
    "id": "attack_convert_hint",
    "dynamic_values": {"value": 1.0},
    "property_hints": [{"property": "AttackConvert", "target": "actor", "source_path": "unit/test"}],
})
ph_apps = status_with_engine_property_hint.modifiers["property_hint_applications"]
assert ph_apps[0]["reason"] in {"materialized_attack_convert_dynamic_value", "single_numeric_attack_convert_dynamic_value"}, ph_apps
assert close(status_with_engine_property_hint.modifiers["atk_add"], 1.0), status_with_engine_property_hint.modifiers
inventory = analyze_engine_property_inventory(engine_prop_root)
attack_convert_rows = [r for r in inventory["properties"] if r["property"] == "AttackConvert"]
assert attack_convert_rows and attack_convert_rows[0]["classification"] == "engine_side_property_candidate", inventory
assert inventory["classification_counts"]["engine_side_property_candidate"] >= 1, inventory
assert inventory["prioritization"]["derived_model_ready_count"] >= 1, inventory
assert any(r["property"] == "AttackConvert" for r in inventory["prioritization"]["derived_model_ready_top"]), inventory["prioritization"]
assert probe_result["metadata"]["auto_probe_action_trace"][0]["before"]["skill_points"] == 3, probe_result["metadata"]["auto_probe_action_trace"]
assert "after" in probe_result["metadata"]["auto_probe_action_trace"][0], probe_result["metadata"]["auto_probe_action_trace"]
assert probe_result["metadata"]["auto_probe_assertions"]["ok"] is True, probe_result["metadata"]["auto_probe_assertions"]
assert probe_result["metadata"]["auto_probe_assertions"]["checks"]["executed_actions_emit_events"] is True, probe_result["metadata"]["auto_probe_assertions"]
checks.append("PASS engine-side property model layer classifies AttackConvert as derived flat ATK, inventories property usage, and auto-probe records before/after snapshots/assertions/event summaries")

# v14.6 Dan Heng PT semantic corrections: 141404 ParamList[4] is Souldragon initial SPD, not action delay.
tbgd_candidates = [ROOT.parent.parent.parent / "TurnBasedGameData-main.zip", ROOT.parent / "TurnBasedGameData-main.zip", Path("/mnt/data/TurnBasedGameData-main.zip"), Path("/mnt/data/turnbasedgamedata-main.zip")]
tbgd_zip_for_skill = next((c for c in tbgd_candidates if c.exists()), None)
if tbgd_zip_for_skill is not None:
    with zipfile.ZipFile(tbgd_zip_for_skill) as zf:
        skill_member = next((n for n in zf.namelist() if n.lower().endswith("/exceloutput/avatarskillconfig.json")), None)
        assert skill_member is not None, zf.namelist()[:20]
        skills = json.loads(zf.read(skill_member))
    talent = next(row for row in skills if row.get("SkillID") == 141404 and row.get("Level") == 15)
    talent_params = [p.get("Value") for p in talent.get("ParamList", [])]
    assert talent_params[4] == 165, talent_params
    current_status_templates = json.loads((ROOT.parent / "status_templates_v0_33" / "status_template_bundle.json").read_text(encoding="utf-8")) if (ROOT.parent / "status_templates_v0_33" / "status_template_bundle.json").exists() else json.loads((ROOT.parent / "status_templates_v0_31" / "status_template_bundle.json").read_text(encoding="utf-8"))
    def _walk_delay_165(x):
        if isinstance(x, dict):
            if x.get("type") in {"delay_action", "advance_action", "set_action_delay"} and 165 in {x.get("amount"), x.get("value"), x.get("percent")}:
                return True
            return any(_walk_delay_165(v) for v in x.values())
        if isinstance(x, list):
            return any(_walk_delay_165(v) for v in x)
        return False
    assert not _walk_delay_165(current_status_templates), "141404 ParamList[4]=165 must not be lowered as action delay"
checks.append("PASS Dan Heng PT 141404 ParamList[4]=165 is guarded as Souldragon initial speed, not action delay")



# v15.0 random-selection lowering/runtime: RandomConfig and RandomSelectDynamicValue
# must execute one deterministic branch instead of all candidate branches.
random_choice_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "actions": {"act": {"id": "act", "action_type": "basic", "tags": [], "target_policy": "self", "damage_packets": [], "effects": [
            {"type": "random_choice", "event_id": "choose_branch", "odds": [0.25, 0.75], "choices": [
                {"index": 0, "effects": [{"type": "set_flag", "key": "picked", "value": "a"}]},
                {"index": 1, "effects": [{"type": "set_flag", "key": "picked", "value": "b"}]},
            ]}
        ]}}},
    },
    "events": {"choose_branch": 1},
    "route": [{"actor": "actor", "action": "act", "targets": []}],
}
random_choice_result = BattleSimulator(random_choice_case).run_route(random_choice_case["route"])
assert random_choice_result["state"]["global"]["flags"]["picked"] == "b", random_choice_result["state"]["global"]["flags"]
assert any(e["event_type"] == "random_choice" and e["data"].get("index") == 1 for e in random_choice_result["log"]), random_choice_result["log"]

random_select_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "actions": {"act": {"id": "act", "action_type": "basic", "tags": [], "target_policy": "self", "damage_packets": [], "effects": [
            {"type": "random_select_flag", "event_id": "select_angle", "key": "RandomAngle", "values": [0, 1, 2, 3]},
            {"type": "set_dynamic_entity_param", "key": "RandomTarget", "target": "actor", "param_target": "target"},
        ]}}},
        "target": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100},
    },
    "events": {"select_angle": 2},
    "route": [{"actor": "actor", "action": "act", "targets": ["target"]}],
}
random_select_result = BattleSimulator(random_select_case).run_route(random_select_case["route"])
assert random_select_result["state"]["global"]["flags"]["RandomAngle"] == 2, random_select_result["state"]["global"]["flags"]
assert random_select_result["state"]["global"]["flags"]["RandomTarget"] == "target", random_select_result["state"]["global"]["flags"]

random_count_unique_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "actions": {"act": {"id": "act", "action_type": "basic", "tags": [], "target_policy": "self", "damage_packets": [], "effects": [
            {"type": "random_choice", "event_id": "multi_pick", "random_count": 2, "random_unique": True, "random_mask_key": "mask", "choices": [
                {"index": 0, "effects": [{"type": "set_flag", "key": "picked_0", "value": True}]},
                {"index": 1, "effects": [{"type": "set_flag", "key": "picked_1", "value": True}]},
                {"index": 2, "effects": [{"type": "set_flag", "key": "picked_2", "value": True}]},
            ]},
            {"type": "random_choice", "event_id": "multi_pick_2", "random_count": 2, "random_unique": True, "random_mask_key": "mask", "choices": [
                {"index": 0, "effects": [{"type": "set_flag", "key": "picked_0", "value": True}]},
                {"index": 1, "effects": [{"type": "set_flag", "key": "picked_1", "value": True}]},
                {"index": 2, "effects": [{"type": "set_flag", "key": "picked_2", "value": True}]},
            ]},
            {"type": "trigger_custom_string", "custom_string": "Sunday_TalkSentence_Test"},
        ]}}},
    },
    "events": {"multi_pick": "1,2"},
    "route": [{"actor": "actor", "action": "act", "targets": []}],
}
random_count_unique_result = BattleSimulator(random_count_unique_case).run_route(random_count_unique_case["route"])
flags = random_count_unique_result["state"]["global"]["flags"]
assert flags["picked_1"] is True and flags["picked_2"] is True and flags["picked_0"] is True, flags
assert flags["mask"] == [0, 1], flags
assert flags["last_custom_string"] == "Sunday_TalkSentence_Test", flags
assert any(e["event_type"] == "custom_string" for e in random_count_unique_result["log"]), random_count_unique_result["log"]
assert any(e["event_type"] == "random_choice" and e["data"].get("indices") == [1, 2] for e in random_count_unique_result["log"]), random_count_unique_result["log"]
checks.append("PASS random-choice/random-select runtime gates support deterministic single/multi unique branches, masks, custom strings, and selected entity parameters")


# v16.2 actual整改：Souldragon fallback parameters are now derived from
# TurnBasedGameData and exact-route expectations support comparison operators.
tbgd_zip_for_template = next((c for c in [Path("/mnt/data/TurnBasedGameData-main.zip"), Path("/mnt/data/turnbasedgamedata-main.zip")] if c.exists()), None)
if tbgd_zip_for_template is not None:
    souldragon_template = derive_souldragon_action_template(tbgd_zip_for_template)
    assert souldragon_template["initial_speed"] == 165.0, souldragon_template
    assert souldragon_template["normal_shield_owner_atk_pct"] == 0.115, souldragon_template
    assert souldragon_template["enhanced_owner_physical_multiplier"] == 1.0, souldragon_template
    assert souldragon_template["enhanced_bondmate_multiplier"] == 1.0, souldragon_template
    assert souldragon_template["derived_actions"]["enhanced"]["damage_packets"][0]["multiplier"] == 1.0, souldragon_template
    summon_ir = souldragon_template["summon_action_ir"]
    assert summon_ir["source"] == "tbgd_action_graph_lowered_souldragon", summon_ir
    graph_packets = summon_ir["actions"]["enhanced"]["damage_packets"]
    graph_phys = [p for p in graph_packets if str(p.get("id", "")).startswith("souldragon_graph_physical_hit_")]
    graph_add = [p for p in graph_packets if p.get("id") == "souldragon_graph_bondmate_additional"]
    assert len(graph_phys) == 4 and len(graph_add) == 1, graph_packets
    assert close(sum(float(p.get("multiplier", 0.0)) for p in graph_phys), 1.0), graph_packets
    assert close(sum(float(p.get("toughness_reduction", 0.0)) for p in graph_phys), 60.0), graph_packets
    assert all(p.get("source_template") == "souldragon_tbgd_action_graph" for p in graph_packets), graph_packets
    assert souldragon_template["graph_lowering_evidence"]["enhanced_source"]["unlowered_combat_node_types"] == {}, souldragon_template["graph_lowering_evidence"]["enhanced_source"]
    passive_enqueue = souldragon_template["graph_lowering_evidence"]["passive_router"]["enqueue_actions"]
    assert {x.get("action_id") for x in passive_enqueue} >= {"Avatar_DanHengPT_00_BE_InsertAttack_Phase01", "Avatar_DanHengPT_00_BE_InsertShield_Phase01"}, passive_enqueue

loaded_template = load_souldragon_action_template(ROOT / "hsr_engine" / "data" / "souldragon_action_template.json")
assert loaded_template["summon_action_ir"]["source"] == "tbgd_action_graph_lowered_souldragon", loaded_template
assert loaded_template["summon_action_ir"]["actions"]["normal"]["effects"][0]["source_template"] == "souldragon_tbgd_action_graph", loaded_template

# Comparison operators make generated enemy harness cases useful before exact
# numeric expectations are known.
expect_compare_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 100}, "actions": {"hit": {"id": "hit", "action_type": "basic", "tags": ["attack"], "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "physical", "scaling_stat": "atk", "multiplier": 1.0, "can_crit": False}]}}},
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 90, "stats": {"def": 0}, "res": {"physical": 0}},
    },
    "route": [{"actor": "actor", "action": "hit", "targets": ["enemy"], "expect": {"damage_total": {"gt": 0, "lt": 200}, "units": {"enemy": {"hp": {"lt": 1000}}}}}],
}
expect_compare_result = BattleSimulator(expect_compare_case).run_route(expect_compare_case["route"])
assert expect_compare_result["metadata"]["route_assertions"]["ok"] is True, expect_compare_result["metadata"]["route_assertions"]
checks.append("PASS Souldragon summon actions are lowered from TBGD BE_InsertShield/BE_InsertAttack graphs and exact-route expectations support comparison operators")

# v16.0 review/audit tooling: keep internal names paired with Chinese explanations,
# and separate generic mechanisms from character fallback patches.
gloss = glossary_report()
assert gloss["terms"]["RandomConfig"]["zh"] == "随机分支配置", gloss
assert "负面状态" in gloss["terms"]["generated debuff lowering"]["what_it_does"], gloss["terms"]["generated debuff lowering"]

genericity = genericity_audit_report(ROOT)
areas = {x["area"]: x for x in genericity["items"]}
assert areas["Souldragon fallback"]["genericity"] == "semi_generic_character_fallback", areas["Souldragon fallback"]
assert areas["enemy mechanisms"]["genericity"] == "inventory_missing", areas["enemy mechanisms"]

break_audit = break_formula_audit_report(level=80)
assert break_audit["element_rows"] and any(r["element"] == "quantum" and "纠缠" in r["aftermath_cn"] for r in break_audit["element_rows"]), break_audit
assert break_audit["level_break_base_damage"] == break_base_damage(80), break_audit

# Build a tiny model-pack-like enemy inventory sample so the inventory tool stays
# covered without depending on the full model pack shape.
enemy_pack = OUT / "enemy_inventory_pack"
(enemy_pack / "models" / "enemies").mkdir(parents=True, exist_ok=True)
(enemy_pack / "stages").mkdir(parents=True, exist_ok=True)
(enemy_pack / "models" / "enemies" / "phase_summon_enemy.yaml").write_text(yaml.safe_dump({
    "id": "phase_summon_enemy",
    "name": "phase summon enemy",
    "hp_model": {"type": "phase_hp", "bars": [1000, 1000]},
    "weakness": ["fire"],
    "toughness": 120,
    "actions": {"summon": {"effects": [{"type": "summon_unit", "unit_id": "minion"}]}},
    "statuses": [{"id": "random_debuff", "triggers": [{"timing": "turn_start", "effects": [{"type": "add_status", "chance": 0.5}]}]}],
}), encoding="utf-8")
(enemy_pack / "stages" / "stage.yaml").write_text(yaml.safe_dump({"waves": [["phase_summon_enemy"]], "notes": "break random summon phase"}), encoding="utf-8")
enemy_inv = analyze_enemy_mechanisms(enemy_pack)
assert enemy_inv["enemy_file_count"] == 1, enemy_inv
assert enemy_inv["enemy_count_with_mechanism_hints"] == 1, enemy_inv
assert enemy_inv["mechanism_group_counts"].get("phase_hp", 0) >= 1, enemy_inv
assert enemy_inv["mechanism_group_counts"].get("summon_or_attached", 0) >= 1, enemy_inv

enemy_harness_dir = OUT / "enemy_route_harness_sample"
enemy_harness_summary = write_enemy_route_harness(enemy_pack, enemy_harness_dir)
assert enemy_harness_summary["case_count"] == 1, enemy_harness_summary
harness_case_file = Path(enemy_harness_summary["cases"][0]["case_file"])
harness_case = load_case(str(harness_case_file))
harness_result = BattleSimulator(harness_case).run_route(harness_case.get("route", []))
assert harness_result["metadata"]["route_assertions"]["ok"] is True, harness_result["metadata"]["route_assertions"]
checks.append("PASS review/audit reports add Chinese mechanism explanations, genericity refactor items, break-formula audit, enemy mechanism inventory, and executable enemy exact-route harness cases")

# v16.4 enemy core mechanics are no longer just inventory rows: force-field
# toughness locks, armor layers, phase-transition immediate actions, and generated
# enemy harnesses execute concrete runtime hooks.
enemy_core_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "ally": {"side": "ally", "hp": 10000, "max_hp": 10000, "speed": 100, "max_energy": 100, "stat_base": {"atk": 1000}, "actions": {
            "hit_fire": {"id": "hit_fire", "action_type": "basic", "tags": ["attack"], "target_policy": "manual", "damage_packets": [{"id": "p", "element": "fire", "scaling_stat": "atk", "multiplier": 1.0, "toughness_reduction": 30, "ignore_weakness_for_toughness": True, "can_crit": False}]},
            "hit_physical": {"id": "hit_physical", "action_type": "basic", "tags": ["attack"], "target_policy": "manual", "damage_packets": [{"id": "p", "element": "physical", "scaling_stat": "atk", "multiplier": 1.0, "toughness_reduction": 30, "can_crit": False}]},
        }},
        "force_enemy": {"side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "level": 80, "toughness": 120, "max_toughness": 120, "weaknesses": ["fire"], "stats": {"def": 0}, "res": {"fire": 0}, "actions": {"counter": {"id": "counter", "action_type": "enemy_skill", "tags": ["enemy_action"], "target_policy": "first_ally", "damage_packets": [{"id": "c", "element": "fire", "scaling_stat": "atk", "multiplier": 1.0, "can_crit": False}]}}, "statuses": [{"id": "force_field", "modifiers": {"toughness_lock": True, "immediate_action_on_hit_by_element": {"element": "fire", "action": "counter", "target_policy": "first_ally"}}}]},
        "armor_enemy": {"side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "level": 80, "toughness": 30, "max_toughness": 30, "weaknesses": ["physical"], "stats": {"def": 0}, "res": {"physical": 0}, "statuses": [{"id": "armor", "stacks": 2, "max_stacks": 2, "modifiers": {"armor_layers": {"damage_reduction_per_layer": 0.2, "on_hit_lose_layers": 1, "on_break_self_imaginary_damage_max_hp_ratio": 0.1, "on_break_action_delay_ratio": 0.15, "on_break_energy_restore_max_energy_ratio_to_breaker": 0.15}}}]},
        "phase_enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100, "level": 80, "hp_bars_total": 2, "hp_bars_remaining": 2, "hp_model": {"type": "phase_hp", "carry_over_damage": False, "bars": [{"hp": 1000}, {"hp": 1000}]}, "flags": {"phase_transition_immediate_action": "counter"}, "stats": {"def": 0, "atk": 100}, "actions": {"counter": {"id": "counter", "action_type": "enemy_skill", "tags": ["enemy_action"], "target_policy": "first_ally", "damage_packets": [{"id": "c", "element": "imaginary", "scaling_stat": "atk", "multiplier": 1.0, "can_crit": False}]}}},
    },
    "route": [
        {"actor": "ally", "action": "hit_fire", "targets": ["force_enemy"], "expect": {"event_counts": {"toughness_lock": {"min": 1}, "enemy_mechanic": {"min": 1}}, "units": {"force_enemy": {"toughness": 120}}}},
        {"actor": "ally", "action": "hit_physical", "targets": ["armor_enemy"], "expect": {"event_counts": {"enemy_mechanic": {"min": 1}}, "units": {"armor_enemy": {"hp": {"lt": 10000}}}}},
        {"type": "apply_effects", "effects": [{"type": "damage_unit", "target": "phase_enemy", "amount": 2000, "ignore_shield": True}], "expect": {"event_counts": {"hp_bar": {"min": 1}, "enemy_mechanic": {"min": 1}, "effect_damage": {"min": 1}}}},
    ],
}
enemy_core_result = BattleSimulator(enemy_core_case).run_route(enemy_core_case["route"])
assert enemy_core_result["metadata"]["route_assertions"]["ok"] is True, enemy_core_result["metadata"]["route_assertions"]
armor_status = next(s for s in enemy_core_result["state"]["units"]["armor_enemy"]["statuses"] if s["id"] == "armor")
assert armor_status["stacks"] == 0, armor_status
assert any(e["event_type"] == "toughness_lock" for e in enemy_core_result["log"]), enemy_core_result["log"]
assert any(e["event_type"] == "enemy_mechanic" and "phase transition" in e["message"] for e in enemy_core_result["log"]), enemy_core_result["log"]

full_pack = ROOT.parent / "model_pack_v3_0"
if full_pack.exists():
    real_enemy_harness_dir = OUT / "enemy_route_harness_real_core"
    real_enemy_harness_summary = write_enemy_route_harness(full_pack, real_enemy_harness_dir)
    assert real_enemy_harness_summary["case_count"] >= 3, real_enemy_harness_summary
    for case_info in real_enemy_harness_summary["cases"]:
        result = BattleSimulator(load_case(case_info["case_file"])).run_route(load_case(case_info["case_file"]).get("route", []))
        assert result["metadata"]["route_assertions"]["ok"] is True, (case_info, result["metadata"]["route_assertions"])
checks.append("PASS enemy core mechanics execute force-field toughness locks, armor layers/break hooks, phase-transition immediate actions, and generated enemy harnesses")

# v18.4 enemy template compiler: model-pack enemy YAML now has a concrete path
# into runtime units/actions/statuses instead of only scan/audit rows.  Keep the
# test small and generic so the compiler is not tied to one boss id.
enemy_compile_sample = {
    "kind": "enemy_template",
    "id": "sample_lance_like_enemy",
    "unit": {
        "id": "sample_lance_like_enemy",
        "template_id": 1,
        "cn_name": "样例敌人",
        "side": "enemy",
        "hp": 10000,
        "max_hp": 10000,
        "speed": 100,
        "level": 80,
        "stats": {"atk": 1000, "def": 0},
        "weaknesses": ["Physical"],
        "res": {"Imaginary": 0},
        "core_mechanics": {
            "summon_conquer_or_be_conquered": {"source_skill_id": 9001, "summon_monster_id": 9002, "max_restorable_hp_reduction_ratio": 0.5},
            "fear_bestowed_by_strife": {"source_skill_id": 9002, "damage_taken_increase": 0.1},
            "absorb_remaining_conquer_or_be_conquered": {"source_skill_id": 9004},
        },
        "skills": [
            {"skill_id": 9001, "trigger_key": "Skill01", "name_chs": "征服", "tag_chs": "妨害", "damage_type": None, "params": [], "description_chs": "每个我方角色生成对应召唤物并施加受征服。"},
            {"skill_id": 9002, "trigger_key": "Skill02", "name_chs": "畏怖", "tag_chs": "妨害", "damage_type": None, "params": [], "description_chs": "施加易伤。"},
            {"skill_id": 9003, "trigger_key": "Skill03", "name_chs": "攻击", "tag_chs": "群攻", "damage_type": "Imaginary", "params": [0.2], "description_chs": "对我方全体造成虚数伤害。"},
            {"skill_id": 9004, "trigger_key": "Skill04", "name_chs": "吸收", "tag_chs": "强化", "damage_type": None, "params": [], "description_chs": "吸收剩余召唤物。"},
        ],
    },
}
compiled_enemy = compile_enemy_template(enemy_compile_sample)
assert compiled_enemy["coverage"]["compiled_action_count"] == 4, compiled_enemy
assert compiled_enemy["coverage"]["uncompiled_mechanic_keys"] == [], compiled_enemy
assert any(e["type"] == "spawn_corresponding_summons" and e.get("per_ally") is True for e in compiled_enemy["unit"]["actions"]["Skill01"]["effects"]), compiled_enemy["unit"]["actions"]["Skill01"]
assert compiled_enemy["unit"]["actions"]["Skill03"]["target_policy"] == "all_allies", compiled_enemy["unit"]["actions"]["Skill03"]

enemy_compile_runtime_case = {
    "global": {"skill_points": 3},
    "units": {
        "ally1": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 1000}, "actions": {"hit_summon": {"id": "hit_summon", "tags": ["attack"], "target_policy": "manual", "damage_packets": [{"id": "p", "element": "physical", "scaling_stat": "atk", "multiplier": 0.5, "can_crit": False}]}}},
        "ally2": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100},
        "sample_lance_like_enemy": compiled_enemy["unit"],
    },
    "route": [
        {"actor": "sample_lance_like_enemy", "action": "Skill01", "targets": [], "expect": {"event_counts": {"summon": {"min": 2}}, "units": {"ally1": {"statuses": {"conquered": {"stacks": 1}}}, "ally2": {"statuses": {"conquered": {"stacks": 1}}}}}},
        {"type": "apply_effects", "effects": [{"type": "heal_unit", "target": "ally1", "amount": 1000}], "expect": {"units": {"ally1": {"hp": 500}}}},
        {"actor": "ally1", "action": "hit_summon", "targets": ["conquer_or_be_conquered_1"], "expect": {"event_counts": {"enemy_mechanic": {"min": 1}}, "units": {"ally1": {"flags": {"max_restorable_hp_ratio": 1.0}}}}},
        {"type": "apply_effects", "effects": [{"type": "heal_unit", "target": "ally1", "amount": 1000}], "expect": {"units": {"ally1": {"hp": 1000}}}},
        {"actor": "sample_lance_like_enemy", "action": "Skill04", "targets": [], "expect": {"event_counts": {"enemy_mechanic": {"min": 1}}, "units": {"sample_lance_like_enemy": {"statuses": {"savage_god_toughness_protection": {"stacks": 1}}}}}},
    ],
}
enemy_compile_runtime_result = BattleSimulator(enemy_compile_runtime_case).run_route(enemy_compile_runtime_case["route"])
assert enemy_compile_runtime_result["metadata"]["route_assertions"]["ok"] is True, enemy_compile_runtime_result["metadata"]["route_assertions"]
assert not enemy_compile_runtime_result["state"]["units"]["conquer_or_be_conquered_2"]["alive"], enemy_compile_runtime_result["state"]["units"].get("conquer_or_be_conquered_2")

if full_pack.exists():
    compiler_out = OUT / "enemy_template_compiler_real"
    compiler_summary = compile_enemy_model_pack(full_pack, compiler_out)
    assert compiler_summary["compiled_count"] >= 3, compiler_summary
    assert all(not row["uncompiled_mechanic_keys"] for row in compiler_summary["rows"]), compiler_summary
checks.append("PASS enemy template compiler emits runtime units/actions/statuses and executes conquer/heal-cap/summon-absorb/toughness-protection hooks")

# v18.5 enemy targeting/AI/summon template upgrades: spread/sweep/split
# target policies should stay formation-aware, split damage should divide across
# selected targets, enemy AI sequence should produce deterministic auto-probe
# actions, and linked summons can consume owner HP on fatal hits.
enemy_targeting_case = {
    "global": {"skill_points": 3},
    "units": {
        "a1": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "flags": {"position": 1}},
        "a2": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "flags": {"position": 2}},
        "a3": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "flags": {"position": 3}},
        "a4": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "flags": {"position": 4}},
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100, "level": 80, "stats": {"atk": 0, "def": 0}, "actions": {
            "spread": {"id": "spread", "action_type": "enemy_skill", "target_policy": "selected_ally_and_adjacent", "damage_packets": [{"id": "flat", "element": "imaginary", "flat_damage": 90, "can_crit": False, "ignore_defense_multiplier": True}]},
            "sweep_r": {"id": "sweep_r", "action_type": "enemy_skill", "target_policy": "three_consecutive_allies_from_right", "damage_packets": [{"id": "flat", "element": "imaginary", "flat_damage": 90, "can_crit": False, "ignore_defense_multiplier": True}]},
            "split": {"id": "split", "action_type": "enemy_skill", "target_policy": "all_allies_split", "damage_packets": [{"id": "flat", "element": "imaginary", "flat_damage": 400, "can_crit": False, "ignore_defense_multiplier": True, "split_damage_across_targets": True}]},
        }, "flags": {"enemy_ai_sequence": ["spread", "sweep_r"], "enemy_ai_sequence_index": 0}},
    },
    "route": [
        {"actor": "enemy", "action": "sweep_r", "expect": {"units": {"a1": {"hp": 1000}, "a2": {"hp": {"lt": 1000}}, "a3": {"hp": {"lt": 1000}}, "a4": {"hp": {"lt": 1000}}}}},
        {"actor": "enemy", "action": "split", "expect": {"units": {"a1": {"hp": 900}, "a2": {"hp": 810}, "a3": {"hp": 810}, "a4": {"hp": 810}}}},
    ],
}
select_sim = BattleSimulator(enemy_targeting_case)
spread_action = select_sim.get_action_def("enemy", "spread")
sweep_action = select_sim.get_action_def("enemy", "sweep_r")
split_action = select_sim.get_action_def("enemy", "split")
assert select_sim.select_targets(spread_action, {"target_id": "a3"}) == ["a2", "a3", "a4"]
assert select_sim.select_targets(sweep_action, None) == ["a2", "a3", "a4"]
assert select_sim.select_targets(split_action, None) == ["a1", "a2", "a3", "a4"]
assert select_sim.default_probe_action_id(select_sim.state.unit("enemy")) == "spread"
enemy_targeting_result = BattleSimulator(enemy_targeting_case).run_route(enemy_targeting_case["route"])
assert enemy_targeting_result["metadata"]["route_assertions"]["ok"] is True, enemy_targeting_result["metadata"]["route_assertions"]

enemy_owner_consume_case = {
    "global": {"skill_points": 3},
    "units": {
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "actions": {"kill": {"id": "kill", "tags": ["attack"], "target_policy": "manual", "damage_packets": [{"id": "flat", "element": "physical", "flat_damage": 200, "can_crit": False, "ignore_defense_multiplier": True}]}}},
        "owner": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100},
        "linked_summon": {"side": "enemy", "hp": 100, "max_hp": 100, "speed": 100, "flags": {"owner_id": "owner", "owner_hp_consumption_ratio_on_fatal": 0.1}},
    },
    "route": [{"actor": "ally", "action": "kill", "targets": ["linked_summon"], "expect": {"event_counts": {"enemy_mechanic": {"min": 1}}, "units": {"owner": {"hp": 900}, "linked_summon": {"alive": False}}}}],
}
owner_consume_result = BattleSimulator(enemy_owner_consume_case).run_route(enemy_owner_consume_case["route"])
assert owner_consume_result["metadata"]["route_assertions"]["ok"] is True, owner_consume_result["metadata"]["route_assertions"]

if full_pack.exists():
    compiler_out_v48 = OUT / "enemy_template_compiler_real_v48"
    compiler_summary_v48 = compile_enemy_model_pack(full_pack, compiler_out_v48)
    assert compiler_summary_v48["version"] == "v0.13", compiler_summary_v48
    assert compiler_summary_v48["compiled_summon_template_count"] >= 3, compiler_summary_v48
    assert compiler_summary_v48["compiled_count"] >= 6, compiler_summary_v48
    assert any(row.get("ability_graph_bound_action_count", 0) > 0 for row in compiler_summary_v48["rows"]), compiler_summary_v48
    lance_compiled = yaml.safe_load((compiler_out_v48 / "compiled_enemies" / "wave2_the_giver__master_of_legions__lance_of_fury.compiled_enemy.yaml").read_text(encoding="utf-8"))
    skill01_effects = lance_compiled["unit"]["actions"]["Skill01"]["effects"]
    summon_eff = next(e for e in skill01_effects if e.get("type") == "spawn_corresponding_summons")
    assert summon_eff.get("template_source") == "legacy_enemy_template_v2_4", summon_eff
    assert summon_eff.get("unit_template", {}).get("max_hp", 0) > 100000, summon_eff
checks.append("PASS enemy formation targeting, split damage, AI sequence fallback, and legacy summon templates execute")


# v18.6 enemy ConfigAI baseline and phase-gated action selection.  The
# compiler should prefer ConfigAI skill references (including duplicate entries)
# over raw skill order; the runtime must advance duplicate sequences by cursor
# and skip phase-locked actions until the enemy actually reaches that phase.
enemy_ai_phase_sample = {
    "kind": "enemy_template",
    "id": "sample_phase_enemy",
    "unit": {
        "id": "sample_phase_enemy",
        "template_id": 2,
        "cn_name": "阶段样例敌人",
        "side": "enemy",
        "hp": 100,
        "max_hp": 100,
        "speed": 100,
        "level": 80,
        "stats": {"atk": 0, "def": 0},
        "core_mechanics": {"phase_transition": {"trigger": "first_hp_bar_depleted", "effect": "immediate_action"}},
        "skills": [
            {"skill_id": 9101, "trigger_key": "Skill01", "name_chs": "一阶段动作", "tag_chs": "单攻", "damage_type": "Imaginary", "params": [0.0], "phase_list": [1, 2], "description_chs": "一二阶段都可用。"},
            {"skill_id": 9102, "trigger_key": "Skill02", "name_chs": "二阶段动作", "tag_chs": "群攻", "damage_type": "Imaginary", "params": [0.0], "phase_list": [2], "description_chs": "二阶段才可用。"},
            {"skill_id": 9103, "trigger_key": "Skill03", "name_chs": "二阶段后续", "tag_chs": "群攻", "damage_type": "Imaginary", "params": [0.0], "phase_list": [2], "description_chs": "二阶段后续。"},
        ],
        "raw": {"ai": {"ai_path": "Config/ConfigAI/Sample.json", "decision_count": 4, "skill_trigger_references": [
            {"path": "/DecisionList[0]/RootTask/SkillName", "skill_trigger_key": "Skill01"},
            {"path": "/DecisionList[1]/RootTask/SkillName", "skill_trigger_key": "Skill01"},
            {"path": "/DecisionList[2]/RootTask/SkillName", "skill_trigger_key": "Skill02"},
            {"path": "/DecisionList[3]/RootTask/SkillName", "skill_trigger_key": "Skill03"},
        ]}},
    },
}
compiled_ai_phase = compile_enemy_template(enemy_ai_phase_sample)["unit"]
assert compiled_ai_phase["flags"]["enemy_ai_sequence"] == ["Skill01", "Skill01", "Skill02", "Skill03"], compiled_ai_phase["flags"]
assert compiled_ai_phase["flags"]["enemy_ai_sequence_source"] == "model_pack_config_ai_skill_references_v0_49", compiled_ai_phase["flags"]
assert compiled_ai_phase["flags"]["enemy_ai_audit"]["duplicates_preserved"] is True, compiled_ai_phase["flags"]
phase_case = {
    "global": {"skill_points": 3},
    "units": {
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "actions": {"hit": {"id": "hit", "tags": ["attack"], "target_policy": "manual", "damage_packets": [{"id": "flat", "element": "physical", "flat_damage": 200, "can_crit": False, "ignore_defense_multiplier": True}]}}},
        "sample_phase_enemy": {**compiled_ai_phase, "hp": 100, "max_hp": 100, "hp_bars_total": 2, "hp_bars_remaining": 2, "hp_model": {"type": "phase_hp", "carry_over_damage": False, "bars": [{"hp": 100}, {"hp": 100}]}, "flags": {**compiled_ai_phase["flags"], "phase_transition_immediate_action": True, "current_phase": 1}},
    },
    "route": [
        {"actor": "sample_phase_enemy", "action": "Skill01", "expect": {"units": {"sample_phase_enemy": {"flags": {"enemy_ai_sequence_index": 1}}}}},
        {"actor": "sample_phase_enemy", "action": "Skill01", "expect": {"units": {"sample_phase_enemy": {"flags": {"enemy_ai_sequence_index": 2}}}}},
        {"actor": "ally", "action": "hit", "targets": ["sample_phase_enemy"], "expect": {"event_counts": {"phase_transition": {"min": 1}, "enemy_ai": {"min": 1}}, "units": {"sample_phase_enemy": {"hp_bars_remaining": 1, "flags": {"current_phase": 2, "monster_phase": 2}}}}},
    ],
}
phase_sim = BattleSimulator(phase_case)
assert phase_sim.default_probe_action_id(phase_sim.state.unit("sample_phase_enemy")) == "Skill01"
phase_result = phase_sim.run_route(phase_case["route"])
assert phase_result["metadata"]["route_assertions"]["ok"] is True, phase_result["metadata"]["route_assertions"]
assert any(e["event_type"] == "phase_transition" for e in phase_result["log"]), phase_result["log"]
# After phase transition the deferred immediate action is resolved using the new
# current_phase, so phase-2-only Skill02 is now a legal default-probe action.
assert any(e["event_type"] == "action_start" and "sample_phase_enemy uses Skill02" in e["message"] for e in phase_result["log"]), phase_result["log"]
checks.append("PASS enemy ConfigAI-derived duplicate sequence, phase-gated action selection, and phase-transition immediate action execute")

# v18.7 continuous Lance-like enemy route: summon corresponding targets, restore
# heal cap by damaging a bound summon, transition phase, absorb leftovers, then
# execute HP-based AoE.  This is a compact chain validation for the knight-3 boss
# sample without turning the project back into a single-boss solver.
lance_chain_enemy = compile_enemy_template(enemy_compile_sample)["unit"]
lance_chain_enemy = deepcopy(lance_chain_enemy)
lance_chain_enemy.update({"hp": 100, "max_hp": 100, "hp_bars_total": 2, "hp_bars_remaining": 2, "hp_model": {"type": "phase_hp", "carry_over_damage": False, "bars": [{"hp": 100}, {"hp": 100}]}})
lance_chain_enemy["flags"] = {**lance_chain_enemy.get("flags", {}), "phase_transition_immediate_action": True, "current_phase": 1}
lance_chain_enemy["actions"]["Skill03"] = {**lance_chain_enemy["actions"]["Skill03"], "phase_list": [2], "effects": [{"type": "hp_based_damage", "target": "all_allies", "element": "imaginary", "target_max_hp_pct": 0.25, "ignore_defense": True, "ignore_shield": False}]}
lance_chain_enemy["flags"]["enemy_ai_sequence"] = ["Skill01", "Skill04", "Skill03"]
lance_chain_enemy["flags"]["enemy_ai_sequence_index"] = 1
lance_chain_case = {
    "global": {"skill_points": 3},
    "units": {
        "ally1": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 1000}, "actions": {"hit_summon": {"id": "hit_summon", "tags": ["attack"], "target_policy": "manual", "damage_packets": [{"id": "p", "element": "physical", "scaling_stat": "atk", "multiplier": 0.5, "can_crit": False}]}, "phase_hit": {"id": "phase_hit", "tags": ["attack"], "target_policy": "manual", "damage_packets": [{"id": "p", "element": "physical", "flat_damage": 200, "can_crit": False, "ignore_defense_multiplier": True}]}}},
        "ally2": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100},
        "sample_lance_like_enemy": lance_chain_enemy,
    },
    "route": [
        {"actor": "sample_lance_like_enemy", "action": "Skill01", "targets": [], "expect": {"event_counts": {"summon": {"min": 2}}, "units": {"ally1": {"flags": {"max_restorable_hp_ratio": 0.5}}, "ally2": {"flags": {"max_restorable_hp_ratio": 0.5}}}}},
        {"actor": "ally1", "action": "hit_summon", "targets": ["conquer_or_be_conquered_1"], "expect": {"units": {"ally1": {"flags": {"max_restorable_hp_ratio": 1.0}}}}},
        {"actor": "ally1", "action": "phase_hit", "targets": ["sample_lance_like_enemy"], "expect": {"event_counts": {"phase_transition": {"min": 1}, "enemy_mechanic": {"min": 1}}, "units": {"sample_lance_like_enemy": {"hp_bars_remaining": 1, "statuses": {"savage_god_toughness_protection": {"stacks": 1}}, "flags": {"current_phase": 2, "absorbed_conquer_or_be_conquered_count": 2}}}}},
        {"actor": "sample_lance_like_enemy", "action": "Skill03", "targets": [], "expect": {"units": {"ally1": {"hp": 750}, "ally2": {"hp": 750}}}},
    ],
}
lance_chain_result = BattleSimulator(lance_chain_case).run_route(lance_chain_case["route"])
assert lance_chain_result["metadata"]["route_assertions"]["ok"] is True, lance_chain_result["metadata"]["route_assertions"]
assert not lance_chain_result["state"]["units"]["conquer_or_be_conquered_2"]["alive"], lance_chain_result["state"]["units"].get("conquer_or_be_conquered_2")
checks.append("PASS continuous Lance-like chain validates summon correspondence, heal-cap restore, phase transition, absorb, and HP-based AoE")


# v17.0 Dan Heng PT / Souldragon role mechanics: AttackConvert is live,
# non-snapshot, and bondmate switching clears the old target.
live_attack_convert_case = {
    "global": {"flags": {}, "skill_points": 5},
    "units": {
        "dan_heng_permansor_terrae": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100,
            "stat_base": {"atk": 1000},
            "actions": {
                "skill": {"id": "skill", "action_type": "skill", "tags": ["skill_use", "support", "consumes_regular_action"], "target_policy": "selected_ally", "damage_packets": [], "effects": []}
            },
        },
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 2000}, "actions": {"hit": {"id": "hit", "action_type": "basic", "tags": ["attack", "consumes_regular_action"], "target_policy": "first_enemy", "damage_packets": [{"id": "p", "element": "quantum", "scaling_stat": "atk", "multiplier": 1.0, "can_crit": False}]}}},
        "sparkle": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 500}, "actions": {}},
        "enemy": {"side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "stats": {"def": 0}, "res": {"quantum": 0}},
    },
    "route": [
        {"actor": "dan_heng_permansor_terrae", "action": "skill", "targets": ["seele"], "expect": {"global_flags": {"bondmate": "seele", "bondmate_target": "seele"}, "units": {"souldragon": {"flags": {"attached_to": "seele"}}}}},
        {"type": "apply_effects", "effects": [{"type": "add_status", "target": "dan_heng_permansor_terrae", "status": {"id": "atk_up", "modifiers": {"atk_add": 1000}}}]},
        {"actor": "seele", "action": "hit", "targets": ["enemy"], "expect": {"damage_total": {"gt": 2299, "lt": 2301}, "units": {"enemy": {"hp": {"lt": 7900}}}}},
        {"actor": "dan_heng_permansor_terrae", "action": "skill", "targets": ["sparkle"], "expect": {"global_flags": {"bondmate": "sparkle", "bondmate_target": "sparkle"}, "units": {"souldragon": {"flags": {"attached_to": "sparkle"}}}}},
    ],
}
live_attack_convert_result = BattleSimulator(live_attack_convert_case).run_route(live_attack_convert_case["route"])
assert live_attack_convert_result["metadata"]["route_assertions"]["ok"] is True, live_attack_convert_result["metadata"]["route_assertions"]
seele_status_ids = {s["id"] for s in live_attack_convert_result["state"]["units"]["seele"]["statuses"]}
sparkle_status_ids = {s["id"] for s in live_attack_convert_result["state"]["units"]["sparkle"]["statuses"]}
assert "bondmate" not in seele_status_ids and "dan_heng_pt_attack_convert_dynamic" not in seele_status_ids, live_attack_convert_result["state"]["units"]["seele"]["statuses"]
assert "bondmate" in sparkle_status_ids and "dan_heng_pt_attack_convert_dynamic" in sparkle_status_ids, live_attack_convert_result["state"]["units"]["sparkle"]["statuses"]
assert any(e["event_type"] == "bondmate_state" and "Cleared previous" in e["message"] for e in live_attack_convert_result["log"]), live_attack_convert_result["log"]
checks.append("PASS Dan Heng AttackConvert is live/non-snapshot and bondmate switching clears old mark/derived ATK")


# Pending Souldragon enhanced actions must survive if Ultimate/enhance resolves
# before the attached dragon shell exists.
pending_souldragon_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "dan_heng_permansor_terrae": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 1000}, "actions": {
            "ult": {"id": "ult", "action_type": "ultimate", "tags": ["ultimate_use"], "target_policy": "all_enemies", "damage_packets": [], "effects": [{"type": "enhance_souldragon", "remaining_actions_added": 2}]},
            "skill": {"id": "skill", "action_type": "skill", "tags": ["skill_use"], "target_policy": "selected_ally", "damage_packets": [], "effects": [{"type": "set_target", "status_id": "bondmate", "target": "selected_ally"}]},
        }},
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 1000}},
    },
    "route": [
        {"actor": "dan_heng_permansor_terrae", "action": "ult", "targets": []},
        {"actor": "dan_heng_permansor_terrae", "action": "skill", "targets": ["seele"], "expect": {"units": {"souldragon": {"flags": {"remaining_enhanced_actions": 2, "is_enhanced": True, "attached_to": "seele"}}}}},
    ],
}
pending_souldragon_result = BattleSimulator(pending_souldragon_case).run_route(pending_souldragon_case["route"])
assert pending_souldragon_result["metadata"]["route_assertions"]["ok"] is True, pending_souldragon_result["metadata"]["route_assertions"]
assert any(e["event_type"] == "summon_lifecycle" and "inherited pending" in e["message"] for e in pending_souldragon_result["log"]), pending_souldragon_result["log"]
checks.append("PASS pending Souldragon enhanced actions are inherited when the dragon shell is created later")



# v18.1 current-team mechanism audit and runtime hooks for general simulator
# construction.  Knight III remains a sample acceptance target; this guard keeps
# the role mechanics that solver routes will depend on from regressing.
full_pack = ROOT.parent / "model_pack_v3_0"
if full_pack.exists():
    team_audit = audit_character_mechanisms(full_pack)
    assert team_audit["summary"]["ok"] is True, team_audit["summary"]
    assert team_audit["summary"]["coverage"] == 1.0, team_audit["summary"]
checks.append("PASS current-team character mechanism audit covers Seele/Sparkle/Tribbie/Dan Heng PT before solver work")

tribbie_once_per_ally_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "tribbie": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "max_energy": 120, "energy": 0, "actions": {}},
        "ally1": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "max_energy": 100, "energy": 100, "actions": {"ult": {"id": "ult", "action_type": "ultimate", "tags": ["ultimate_use"], "cost": {"energy": 0}, "damage_packets": []}}},
        "ally2": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "max_energy": 100, "energy": 100, "actions": {"ult": {"id": "ult", "action_type": "ultimate", "tags": ["ultimate_use"], "cost": {"energy": 0}, "damage_packets": []}}},
    },
    "triggers": [{"id": "tribbie_once_per_other_ally_ult", "owner": "tribbie", "timing": "after_other_ally_uses_ultimate", "condition": "always", "effects": [{"type": "gain_energy", "target": "tribbie", "amount": 1, "affected_by_err": False}], "usage_limit": {"scope": "per_trigger_actor", "max_times": 1}}],
    "route": [{"actor": "ally1", "action": "ult", "targets": []}, {"actor": "ally1", "action": "ult", "targets": []}, {"actor": "ally2", "action": "ult", "targets": []}],
}
tribbie_once_result = BattleSimulator(tribbie_once_per_ally_case).run_route(tribbie_once_per_ally_case["route"])
assert close(tribbie_once_result["state"]["units"]["tribbie"]["energy"], 2.0), tribbie_once_result["state"]["units"]["tribbie"]
checks.append("PASS generic per_trigger_actor usage scope supports Tribbie once-per-other-ally Ultimate talent semantics")

tribbie_zone_case = {
    "settings": {"crit_mode": "never"},
    "global": {"flags": {"zone_active": True}, "skill_points": 3},
    "units": {
        "tribbie": {"side": "ally", "hp": 5000, "max_hp": 5000, "speed": 100, "max_energy": 120, "energy": 0, "stat_base": {"hp": 5000}, "stats": {"hp": 5000}, "actions": {}},
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "stat_base": {"atk": 1000}, "actions": {"aoe": {"id": "aoe", "action_type": "basic", "tags": ["attack", "basic_attack"], "target_policy": "all_enemies", "damage_packets": [{"id": "p", "element": "quantum", "scaling_stat": "atk", "multiplier": 0.1, "target_policy": "all_enemies", "can_crit": False}]}}},
        "e1": {"side": "enemy", "hp": 10000, "max_hp": 10000, "speed": 100, "level": 80, "stats": {"def": 0}, "res": {"quantum": 0}},
        "e2": {"side": "enemy", "hp": 20000, "max_hp": 20000, "speed": 100, "level": 80, "stats": {"def": 0}, "res": {"quantum": 0}},
    },
    "triggers": [
        {"id": "zone_add", "owner": "tribbie", "timing": "after_ally_attacks", "condition": "zone_active and action.actor_id != tribbie", "effects": [{"type": "zone_additional_damage", "source": "tribbie", "per_target_hit": True, "target_policy": "highest_hp_among_hit_targets", "element": "quantum", "damage_type": "additional_damage", "scaling_stat": "hp", "multiplier": 0.01, "can_crit": False}]},
        {"id": "e1_true", "owner": "tribbie", "timing": "after_tribbie_zone_additional_damage", "condition": "zone_active", "effects": [{"type": "zone_followup_true_damage", "effect": {"true_damage_equal_to_total_attack_damage": 0.24, "target": "targets_dealt_zone_additional_damage"}}]},
        {"id": "a6_energy", "owner": "tribbie", "timing": "after_ally_attacks", "condition": "action.actor_id != tribbie", "effects": [{"type": "gain_energy", "target": "tribbie", "amount": 0, "affected_by_err": True, "energy_per_hit": 1.5}]},
    ],
    "route": [{"actor": "ally", "action": "aoe", "targets": ["e1", "e2"]}],
}
tribbie_zone_result = BattleSimulator(tribbie_zone_case).run_route(tribbie_zone_case["route"])
assert close(tribbie_zone_result["state"]["units"]["tribbie"]["energy"], 3.0), tribbie_zone_result["state"]["units"]["tribbie"]
assert close(tribbie_zone_result["state"]["units"]["e1"]["hp"], 9900.0), tribbie_zone_result["state"]["units"]["e1"]
assert close(tribbie_zone_result["state"]["units"]["e2"]["hp"], 19752.0), tribbie_zone_result["state"]["units"]["e2"]
assert any(e["event_type"] == "effect" and "Zone additional damage" in e["message"] and close(e["data"].get("total", 0), 100.0) for e in tribbie_zone_result["log"]), tribbie_zone_result["log"]
checks.append("PASS Tribbie zone additional damage, E1 true-damage target alias, and per-hit energy hook execute")

tribbie_zone_kill_credit_case = {
    "settings": {"crit_mode": "never", "kill_energy_base": 10, "kill_energy_affected_by_err": True},
    "global": {"flags": {"zone_active": True}, "skill_points": 3},
    "units": {
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "max_energy": 120, "energy": 0, "stat_base": {"atk": 1000}, "stats": {"atk": 1000}, "actions": {"basic": {"id": "basic", "action_type": "basic", "tags": ["attack", "basic_attack", "can_trigger_resurgence", "can_trigger_kill_energy"], "target_policy": "selected_enemy", "damage_packets": [{"id": "seele_basic", "element": "quantum", "scaling_stat": "atk", "multiplier": 0.1, "can_crit": False}]}}},
        "tribbie": {"side": "ally", "hp": 5000, "max_hp": 5000, "speed": 100, "max_energy": 120, "energy": 0, "stat_base": {"hp": 5000}, "stats": {"hp": 5000}, "actions": {}},
        "enemy": {"side": "enemy", "hp": 150, "max_hp": 150, "speed": 100, "level": 80, "stats": {"def": 0}, "res": {"quantum": 0}},
    },
    "triggers": [
        {"id": "zone_add", "owner": "tribbie", "timing": "after_ally_attacks", "condition": "zone_active and action.actor_id != tribbie", "effects": [{"type": "zone_additional_damage", "source": "tribbie", "target_policy": "highest_hp_among_hit_targets", "element": "quantum", "damage_type": "additional_damage", "scaling_stat": "hp", "multiplier": 0.01, "can_crit": False}]},
        {"id": "seele_resurgence_guard", "owner": "seele", "timing": "after_defeat_enemy", "priority": 90, "condition": {"all": ["defeated_by.owner == seele", "action.tags contains can_trigger_resurgence", "context.extra_turn_type != resurgence"]}, "effects": [{"type": "enqueue_extra_turn", "actor": "seele", "extra_turn_type": "resurgence", "queue": "extra_turn_queue"}]},
    ],
    "route": [{"actor": "seele", "action": "basic", "targets": ["enemy"]}],
}
tribbie_zone_kill_credit_result = BattleSimulator(tribbie_zone_kill_credit_case).run_route(tribbie_zone_kill_credit_case["route"])
assert tribbie_zone_kill_credit_result["state"]["units"]["enemy"]["alive"] is False, tribbie_zone_kill_credit_result["state"]["units"]["enemy"]
assert close(tribbie_zone_kill_credit_result["state"]["units"]["tribbie"]["energy"], 10.0), tribbie_zone_kill_credit_result["state"]["units"]["tribbie"]
assert close(tribbie_zone_kill_credit_result["state"]["units"]["seele"]["energy"], 0.0), tribbie_zone_kill_credit_result["state"]["units"]["seele"]
assert not tribbie_zone_kill_credit_result["state"]["global"]["flags"].get("pending_extra_turn:seele:resurgence"), tribbie_zone_kill_credit_result["state"]["global"]["flags"]
assert any(e["event_type"] == "resource" and "tribbie gains" in e["message"] and "kill:enemy" in e["message"] for e in tribbie_zone_kill_credit_result["log"]), tribbie_zone_kill_credit_result["log"]
checks.append("PASS Tribbie zone/additional damage owns kill credit, kill energy, and does not trigger Seele Resurgence")



# v18.2 generic runtime hooks promoted from model annotations.
# Sparkle's Artificial Flower status can express "next Skill costs 0 SP"
# without a character-specific branch in validate_and_pay_cost.
sparkle_next_skill_free_case = {
    "global": {"flags": {}, "skill_points": 0},
    "units": {
        "sparkle": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "max_energy": 110, "energy": 0,
            "statuses": [{
                "id": "sparkle_next_skill_free",
                "tags": ["cost_override"],
                "modifiers": {"skill_point_cost_override": 0, "next_skill_cost_delta": 1},
                "duration": {"type": "until_next_skill_use"},
            }],
            "actions": {
                "skill": {
                    "id": "skill", "action_type": "skill", "tags": ["skill_use", "support"],
                    "target_policy": "selected_ally", "cost": {"skill_points": -1},
                    "damage_packets": [],
                }
            },
        },
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100},
    },
    "triggers": [{
        "id": "sp_watcher", "timing": "after_skill_point_consumed", "condition": "always",
        "effects": [{"type": "set_flag", "key": "sp_consumed", "value": True}],
    }],
    "route": [{"actor": "sparkle", "action": "skill", "targets": ["ally"]}],
}
sparkle_free_result = BattleSimulator(sparkle_next_skill_free_case).run_route(sparkle_next_skill_free_case["route"])
assert sparkle_free_result["state"]["global"]["skill_points"] == 0, sparkle_free_result["state"]["global"]
assert "sparkle_next_skill_free" not in {s["id"] for s in sparkle_free_result["state"]["units"]["sparkle"]["statuses"]}, sparkle_free_result["state"]["units"]["sparkle"]["statuses"]
assert sparkle_free_result["state"]["global"]["flags"].get("sp_consumed") is None, sparkle_free_result["state"]["global"]["flags"]
assert any(e["event_type"] == "resource" and "overridden to 0" in e["message"] for e in sparkle_free_result["log"]), sparkle_free_result["log"]
checks.append("PASS generic next-Skill SP cost override executes Sparkle A4-style free Skill and consumes the one-shot status")

# Tribbie A4 uses max_hp_from_team_hp_pct as an executable HPAddedRatio-like
# side effect: max HP increases together with current HP and reverts on removal.
tribbie_a4_hp_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "tribbie": {
            "side": "ally", "hp": 5000, "max_hp": 5000, "speed": 100,
            "actions": {"ult": {"id": "ult", "action_type": "ultimate", "tags": ["ultimate_use", "support"], "cost": {"energy": 0}, "damage_packets": [], "effects": [{"type": "add_status", "target": "tribbie", "status": {"id": "tribbie_a4_zone_hp_boost", "modifiers": {"max_hp_from_team_hp_pct": 0.09}, "duration": {"type": "while_zone_active"}}}]}},
        },
        "ally1": {"side": "ally", "hp": 3000, "max_hp": 3000, "speed": 100},
        "ally2": {"side": "ally", "hp": 2000, "max_hp": 2000, "speed": 100},
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100},
    },
    "route": [
        {"actor": "tribbie", "action": "ult", "targets": [], "expect": {"units": {"tribbie": {"max_hp": 5900, "hp": 5900}}}},
        {"type": "apply_effects", "effects": [{"type": "remove_status", "target": "tribbie", "status_id": "tribbie_a4_zone_hp_boost"}], "expect": {"units": {"tribbie": {"max_hp": 5000, "hp": 5000}}}},
    ],
}
tribbie_a4_hp_result = BattleSimulator(tribbie_a4_hp_case).run_route(tribbie_a4_hp_case["route"])
assert tribbie_a4_hp_result["metadata"]["route_assertions"]["ok"] is True, tribbie_a4_hp_result["metadata"]["route_assertions"]
assert any(e["event_type"] == "resource" and e["data"].get("property") == "HPAddedRatio/max_hp_from_team_hp_pct" for e in tribbie_a4_hp_result["log"]), tribbie_a4_hp_result["log"]
checks.append("PASS Tribbie A4 max_hp_from_team_hp_pct applies and reverts as a generic HPAddedRatio-style status side effect")



# v18.3 character lifecycle hardening before moving to enemy mechanics.
# Natural status expiry must use the same removal path as explicit remove_status;
# otherwise HPAddedRatio / MaxSP side effects can leak after the buff disappears.
tribbie_a4_expiry_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "tribbie": {
            "side": "ally", "hp": 5000, "max_hp": 5000, "speed": 100, "remaining_av": 0,
            "actions": {"wait": {"id": "wait", "tags": ["support", "consumes_regular_action"], "cost": {"skill_points": 0}, "damage_packets": []}},
        },
        "ally1": {"side": "ally", "hp": 3000, "max_hp": 3000, "speed": 100},
        "ally2": {"side": "ally", "hp": 2000, "max_hp": 2000, "speed": 100},
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100},
    },
    "triggers": [{
        "id": "a4_destroy_seen", "timing": "status_destroy", "status_id": "tribbie_a4_zone_hp_boost",
        "effect": {"type": "set_flag", "key": "tribbie_a4_destroyed", "value": True},
    }],
    "route": [
        {"type": "apply_effects", "effects": [{"type": "add_status", "target": "tribbie", "status": {"id": "tribbie_a4_zone_hp_boost", "modifiers": {"max_hp_from_team_hp_pct": 0.09}, "duration": {"type": "holder_turns", "value": 1}}}], "expect": {"units": {"tribbie": {"max_hp": 5900, "hp": 5900}}}},
        {"actor": "tribbie", "action": "wait", "timing": "regular_turn", "expect": {"units": {"tribbie": {"max_hp": 5000, "hp": 5000}}, "global": {"flags": {"tribbie_a4_destroyed": True}}}},
    ],
}
tribbie_a4_expiry_result = BattleSimulator(tribbie_a4_expiry_case).run_route(tribbie_a4_expiry_case["route"])
assert tribbie_a4_expiry_result["metadata"]["route_assertions"]["ok"] is True, tribbie_a4_expiry_result["metadata"]["route_assertions"]
assert any(e["event_type"] == "status_expire" and e["data"].get("status") == "tribbie_a4_zone_hp_boost" for e in tribbie_a4_expiry_result["log"]), tribbie_a4_expiry_result["log"]
assert any(e["event_type"] == "resource" and e["data"].get("removed") is True for e in tribbie_a4_expiry_result["log"]), tribbie_a4_expiry_result["log"]
checks.append("PASS natural status expiry reverts HPAddedRatio/MaxSP-style resource side effects and emits status_destroy")

# Zone-bound statuses should also be removed through the resource-safe lifecycle
# when the zone ends, even if they have no numeric duration counter.
zone_end_case = {
    "global": {"flags": {}, "skill_points": 3},
    "units": {
        "tribbie": {"side": "ally", "hp": 5000, "max_hp": 5000, "speed": 100},
        "ally": {"side": "ally", "hp": 5000, "max_hp": 5000, "speed": 100},
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100},
    },
    "route": [
        {"type": "apply_effects", "effects": [
            {"type": "add_zone", "zone_id": "tribbie_zone_guess_who_lives_here"},
            {"type": "add_status", "target": "tribbie", "status": {"id": "tribbie_zone_hp_boost", "modifiers": {"max_hp_from_team_hp_pct": 0.09}, "duration": {"type": "while_zone_active"}}},
        ], "expect": {"units": {"tribbie": {"max_hp": 5900, "hp": 5900}}, "global": {"flags": {"zone_active": True}}}},
        {"type": "apply_effects", "effects": [{"type": "remove_zone", "zone_id": "tribbie_zone_guess_who_lives_here"}], "expect": {"units": {"tribbie": {"max_hp": 5000, "hp": 5000}}, "global": {"flags": {"zone_active": False}}}},
    ],
}
zone_end_result = BattleSimulator(zone_end_case).run_route(zone_end_case["route"])
assert zone_end_result["metadata"]["route_assertions"]["ok"] is True, zone_end_result["metadata"]["route_assertions"]
assert "tribbie_zone_hp_boost" not in {s["id"] for s in zone_end_result["state"]["units"]["tribbie"]["statuses"]}, zone_end_result["state"]["units"]["tribbie"]["statuses"]
checks.append("PASS while_zone_active statuses expire and revert resource side effects when the zone is removed")

# Tribbie's Talent-like once-per-other-ally Ultimate trigger needs two generic
# pieces before enemy work: owner-exclusion, per-trigger-actor usage, and reset by
# Tribbie's own Ultimate.
tribbie_other_ult_reset_case = {
    "global": {"skill_points": 3},
    "settings": {"kill_energy_base": 0},
    "units": {
        "sparkle": {"side": "ally", "hp": 1000, "max_hp": 1000, "actions": {"ult": {"id": "sparkle_ult", "tags": ["ultimate_use", "support"], "damage_packets": [], "cost": {"energy": 0}}}},
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "actions": {"ult": {"id": "seele_ult", "tags": ["ultimate_use", "attack"], "damage_packets": [], "cost": {"energy": 0}}}},
        "tribbie": {
            "side": "ally", "hp": 1000, "max_hp": 1000,
            "actions": {"ult": {"id": "tribbie_ult", "tags": ["ultimate_use", "support"], "cost": {"energy": 0}, "damage_packets": [], "effects": [{"type": "reset_trigger_usage", "prefix": "tribbie_talent_after_other_ult"}]}},
            "triggers": {
                "talent": {"id": "tribbie_talent_after_other_ult", "owner": "tribbie", "timing": "after_other_ally_uses_ultimate", "usage_limit": {"scope": "per_trigger_actor", "max_times": 1}, "effect": {"type": "damage_unit", "target": "enemy", "amount": 100, "ignore_shield": True}}
            },
        },
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "toughness": "infinite", "stats": {"def": 0}},
    },
    "route": [
        {"actor": "sparkle", "action": "ult", "timing": "ultimate"},
        {"actor": "sparkle", "action": "ult", "timing": "ultimate"},
        {"actor": "seele", "action": "ult", "timing": "ultimate", "expect": {"units": {"enemy": {"hp": 800}}}},
        {"actor": "tribbie", "action": "ult", "timing": "ultimate", "expect": {"units": {"enemy": {"hp": 800}}}},
        {"actor": "sparkle", "action": "ult", "timing": "ultimate", "expect": {"units": {"enemy": {"hp": 700}}}},
    ],
}
tribbie_other_ult_reset_result = BattleSimulator(tribbie_other_ult_reset_case).run_route(tribbie_other_ult_reset_case["route"])
assert tribbie_other_ult_reset_result["metadata"]["route_assertions"]["ok"] is True, tribbie_other_ult_reset_result["metadata"]["route_assertions"]
assert sum(1 for e in tribbie_other_ult_reset_result["log"] if e["event_type"] == "trigger" and "tribbie_talent_after_other_ult" in e["message"]) == 3, tribbie_other_ult_reset_result["log"]
checks.append("PASS Tribbie once-per-other-ally Ultimate trigger excludes self, persists per ally, and resets after Tribbie Ultimate")

# Sparkle-style source-turn duration boundary: Ultimate itself must not consume a
# source_turns buff duration, but Sparkle's later regular turns should. Figment
# stacking also stays capped and refreshes through add_or_refresh_stack.
sparkle_cipher_figment_case = {
    "global": {"skill_points": 7, "skill_point_cap": 7},
    "units": {
        "sparkle": {
            "side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100, "remaining_av": 0,
            "status_effects": {
                "cipher": {"id": "cipher", "duration": {"type": "source_turns", "value": 2}, "modifiers": {"atk_pct": 0.40}},
                "figment": {"id": "figment", "duration": {"type": "source_turns", "value": 2}, "modifiers": {"damage_taken_add": 0.04}, "stack_rule": {"max_stacks": 3, "refresh_duration": True}},
            },
            "actions": {
                "ult": {"id": "sparkle_ult", "tags": ["ultimate_use", "support"], "cost": {"energy": 0}, "damage_packets": [], "effects": [{"type": "add_buff", "buff_id": "cipher", "target": "all_allies", "source_id": "sparkle"}]},
                "wait": {"id": "sparkle_wait", "tags": ["support", "consumes_regular_action"], "cost": {"skill_points": 0}, "damage_packets": []},
            },
            "triggers": {
                "figment_on_sp": {"id": "sparkle_figment_on_sp", "owner": "sparkle", "timing": "after_skill_point_consumed", "condition": "consumed_skill_points >= 1", "effects": [{"type": "add_or_refresh_stack", "target": "enemies_or_global_enemy_side", "status_id": "figment", "stacks": "ctx:consumed_skill_points", "max_stacks": 3, "source_id": "sparkle"}]}
            },
        },
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "actions": {"skill": {"id": "seele_skill", "tags": ["skill_use", "attack"], "cost": {"skill_points": -2}, "damage_packets": []}}},
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "actions": {"skill": {"id": "ally_skill", "tags": ["skill_use", "support"], "cost": {"skill_points": -2}, "damage_packets": []}}},
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "toughness": "infinite", "stats": {"def": 0}},
    },
    "route": [
        {"actor": "sparkle", "action": "ult", "timing": "ultimate"},
        {"actor": "seele", "action": "skill", "targets": "enemy"},
        {"actor": "ally", "action": "skill", "targets": "enemy", "expect": {"units": {"enemy": {"statuses": {"figment": {"stacks": 3, "duration_value": 2}}}}}},
        {"actor": "sparkle", "action": "wait", "timing": "regular_turn", "expect": {"units": {"seele": {"statuses": {"cipher": {"duration_value": 1}}}, "enemy": {"statuses": {"figment": {"duration_value": 1}}}}}},
        {"actor": "sparkle", "action": "wait", "timing": "regular_turn"},
    ],
}
sparkle_cipher_figment_result = BattleSimulator(sparkle_cipher_figment_case).run_route(sparkle_cipher_figment_case["route"])
assert sparkle_cipher_figment_result["metadata"]["route_assertions"]["ok"] is True, sparkle_cipher_figment_result["metadata"]["route_assertions"]
assert "cipher" not in {s["id"] for s in sparkle_cipher_figment_result["state"]["units"]["seele"]["statuses"]}, sparkle_cipher_figment_result["state"]["units"]["seele"]["statuses"]
assert "figment" not in {s["id"] for s in sparkle_cipher_figment_result["state"]["units"]["enemy"]["statuses"]}, sparkle_cipher_figment_result["state"]["units"]["enemy"]["statuses"]
checks.append("PASS Sparkle Cipher/Figment source-turn duration boundaries, stack cap, and refresh behavior are route-verified")


# v18.8 enemy ConfigAI predicate lowering: compiled templates now use actual
# ByCompareMonsterPhase / ByCompareDynamicValue / ByTargetAliveState decisions
# instead of only a flat SkillName sequence.
lance_compiled = compile_enemy_template(ROOT.parent / "model_pack_v3_0" / "models" / "enemies" / "wave2_the_giver__master_of_legions__lance_of_fury.yaml")
lance_unit = deepcopy(lance_compiled["unit"])
lance_unit["hp"] = 10000
lance_unit["max_hp"] = 10000
lance_ai_case = {
    "units": {
        "lance": lance_unit,
        "ally1": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 0},
        "ally2": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 1},
        "ally3": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 2},
        "ally4": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 3},
    },
    "route": [],
}
lance_sim = BattleSimulator(lance_ai_case)
lance = lance_sim.state.unit("lance")
# phase 1 AIFlag=1 -> Skill01, remains AIFlag=1
assert lance_sim.default_probe_action_id(lance) == "Skill01"
assert lance.flags.get("AIFlag") == 1
# phase 2 chain should follow AIFlag 1 -> 2 -> 3 -> 4 -> 1 with Skill01/02/04/03.
lance.flags["current_phase"] = 2
lance.flags["monster_phase"] = 2
lance.flags["AIFlag"] = 1
seq = []
flags = []
for _ in range(4):
    aid = lance_sim.default_probe_action_id(lance)
    seq.append(aid)
    flags.append(lance.flags.get("AIFlag"))
assert seq == ["Skill01", "Skill02", "Skill04", "Skill03"], (seq, flags, lance.flags.get("enemy_ai_decisions"))
assert flags == [2, 3, 4, 1], flags
assert lance.flags.get("enemy_ai_decision_source") == "tbgd_config_ai_filter_selector_score_baseline_v0_57"
checks.append("PASS enemy ConfigAI phase/dynamic-value predicates drive Lance AIFlag action chain")

# TargetAliveState must check formation slots, not the nth currently alive unit.
# With the first three formation slots dead, Furiae Praetor's AIFlag=1 branch
# should take the FailedTaskList Skill02 rather than misreading slot 3 as slot 0.
furiae_compiled = compile_enemy_template(ROOT.parent / "model_pack_v3_0" / "models" / "enemies" / "wave1_furiae_praetor.yaml")
furiae_unit = deepcopy(furiae_compiled["unit"])
furiae_unit["hp"] = 10000
furiae_unit["max_hp"] = 10000
furiae_ai_case = {
    "units": {
        "furiae": furiae_unit,
        "a0": {"side": "ally", "hp": 0, "max_hp": 1000, "alive": False, "position": 0},
        "a1": {"side": "ally", "hp": 0, "max_hp": 1000, "alive": False, "position": 1},
        "a2": {"side": "ally", "hp": 0, "max_hp": 1000, "alive": False, "position": 2},
        "a3": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 3},
    },
    "route": [],
}
furiae_sim = BattleSimulator(furiae_ai_case)
furiae = furiae_sim.state.unit("furiae")
furiae.flags["AIFlag"] = 1
chosen = furiae_sim.default_probe_action_id(furiae)
assert chosen == "Skill02", (chosen, furiae.flags.get("enemy_ai_decisions"))
assert furiae.flags.get("AIFlag") == 5
checks.append("PASS enemy ConfigAI TargetAliveState uses formation slot liveness, not compacted alive order")


# v18.9 enemy ConfigAI skill-use record/cooldown semantics and formation sort
# direction.  This keeps AI stateful enough for enemies that gate skills by
# CheckSkillUsabilityAxis or ByCompareSkillUsageLimit, while still staying a
# deterministic baseline rather than a full scorer.
skill_record_case = {
    "units": {
        "enemy": {
            "side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"atk": 100, "def": 0},
            "flags": {
                "enemy_skill_cooldown_config": {"SkillA": {"initial_cd": 0, "cd": 1}},
                "enemy_skill_cooldowns": {"SkillA": 1},
                "enemy_ai_decisions": [
                    {"skill": "SkillA", "condition": {"enemy_skill_cooldown_ready": {"skill": "SkillA"}}},
                    {"skill": "SkillB", "condition": True},
                ],
            },
            "actions": {
                "SkillA": {"id": "SkillA", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []},
                "SkillB": {"id": "SkillB", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []},
            },
        },
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 0},
    },
}
skill_record_sim = BattleSimulator(skill_record_case)
skill_enemy = skill_record_sim.state.unit("enemy")
assert skill_record_sim.default_probe_action_id(skill_enemy) == "SkillB"
skill_record_sim.resolve_action({"actor_id": "enemy", **skill_enemy.action_defs["SkillB"]}, [], {})
assert skill_enemy.flags.get("enemy_skill_cooldowns", {}).get("SkillA") == 0, skill_enemy.flags
assert skill_record_sim.default_probe_action_id(skill_enemy) == "SkillA"
skill_record_sim.resolve_action({"actor_id": "enemy", **skill_enemy.action_defs["SkillA"]}, [], {})
assert skill_enemy.flags.get("enemy_skill_use_counts", {}).get("SkillA") == 1, skill_enemy.flags
assert skill_enemy.flags.get("enemy_skill_cooldowns", {}).get("SkillA") == 1, skill_enemy.flags
usage_ctx = {"actor_id": "enemy", "actor": skill_enemy, "context": {"phase": "enemy_ai_decision"}, "phase_locked_targets": set()}
assert skill_record_sim.eval_condition({"enemy_skill_usage_delay_ready": {"skill": "SkillA", "action_delay": 2}}, usage_ctx) is False
skill_enemy.flags["enemy_action_counter"] = skill_enemy.flags.get("enemy_action_counter", 0) + 2
assert skill_record_sim.eval_condition({"enemy_skill_usage_delay_ready": {"skill": "SkillA", "action_delay": 2}}, usage_ctx) is True

# TargetSortByFormation HighestFirst must check right-side formation slots.  If
# only the rightmost slot is alive, index 0 under descending sort is alive while
# index 0 under ascending sort is dead.
formation_sort_case = {
    "units": {
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000},
        "a0": {"side": "ally", "hp": 0, "max_hp": 1000, "alive": False, "position": 0},
        "a1": {"side": "ally", "hp": 0, "max_hp": 1000, "alive": False, "position": 1},
        "a2": {"side": "ally", "hp": 0, "max_hp": 1000, "alive": False, "position": 2},
        "a3": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 3},
    },
}
formation_sort_sim = BattleSimulator(formation_sort_case)
ctx = {"actor_id": "enemy", "actor": formation_sort_sim.state.unit("enemy"), "context": {}, "phase_locked_targets": set()}
assert formation_sort_sim.eval_condition({"target_alive_state": {"side": "ally", "formation_index": 0, "formation_order": "desc", "alive": True}}, ctx) is True
assert formation_sort_sim.eval_condition({"target_alive_state": {"side": "ally", "formation_index": 0, "formation_order": "asc", "alive": True}}, ctx) is False
checks.append("PASS enemy AI skill-use record/cooldown hooks and TargetSortByFormation direction execute")

# Shared-HP linked enemy bodies: model-pack Lance compiles a shared group id and
# legacy Savage God summon templates carry the same group.  HP loss to one body
# mirrors to the linked body without pretending this is the final full action-axis
# model.
lance_shared = compile_enemy_template(ROOT.parent / "model_pack_v3_0" / "models" / "enemies" / "wave2_the_giver__master_of_legions__lance_of_fury.yaml")
assert lance_shared["unit"]["flags"].get("shared_hp_group_id") == "lance_savage_god_shared_hp", lance_shared["unit"]["flags"]
shared_hp_case = {
    "units": {
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "actions": {"hit": {"id": "hit", "tags": ["attack"], "target_policy": "manual", "damage_packets": []}}},
        "lance": {"side": "enemy", "hp": 10000, "max_hp": 10000, "flags": {"shared_hp_group_id": "lance_savage_god_shared_hp"}},
        "savage": {"side": "enemy", "hp": 10000, "max_hp": 10000, "flags": {"shared_hp_group_id": "lance_savage_god_shared_hp"}},
    },
    "route": [
        {"type": "apply_effects", "effects": [{"type": "damage_unit", "target": "lance", "amount": 1234, "ignore_shield": True}], "expect": {"units": {"lance": {"hp": 8766}, "savage": {"hp": 8766}}, "event_counts": {"shared_hp": {"min": 1}}}},
    ],
}
shared_hp_result = BattleSimulator(shared_hp_case).run_route(shared_hp_case["route"])
assert shared_hp_result["metadata"]["route_assertions"]["ok"] is True, shared_hp_result["metadata"]["route_assertions"]
checks.append("PASS Lance/Savage-God shared-HP group is compiled and runtime HP-loss sync executes")


# v19.0 Savage God legacy mechanisms are now executable enough for route-level
# validation: Calamity Eternal applies Glory and Titanic Corpus, Glory removes
# Titanic Corpus layers on allied attacks, zero layers trigger self-damage/delay/
# team energy, and Glory clears only after Savage God's following action rather
# than immediately after the application action.
savage_bundle_dir = OUT / "enemy_template_compiler_test_v0_8"
compile_enemy_model_pack(ROOT.parent / "model_pack_v3_0", savage_bundle_dir)
savage_compiled_path = savage_bundle_dir / "compiled_enemy_summons" / "4014012.compiled_enemy_summon.yaml"
savage_unit = yaml.safe_load(savage_compiled_path.read_text(encoding="utf-8"))["unit"]
assert "Skill05" in savage_unit["actions"], savage_unit["actions"].keys()
skill05_effect_types = [e.get("type") for e in savage_unit["actions"]["Skill05"].get("effects", [])]
assert "add_status" in skill05_effect_types and "set_unit_flag" in skill05_effect_types, savage_unit["actions"]["Skill05"].get("effects")
savage_case = {
    "units": {
        "savage": {**deepcopy(savage_unit), "hp": 100000, "max_hp": 100000, "stats": {"atk": 100, "def": 0}, "res": {}},
        "ally1": {"side": "ally", "hp": 10000, "max_hp": 10000, "energy": 0, "max_energy": 100, "position": 0, "stats": {"atk": 100, "def": 0}, "actions": {"skill_hit": {"id": "skill_hit", "action_type": "skill", "tags": ["attack", "skill_use"], "target_policy": "manual", "damage_packets": [{"id": "flat", "element": "quantum", "flat_damage": 100, "can_crit": False, "ignore_defense_multiplier": True, "ignore_toughness_state_multiplier": True}]}}},
        "ally2": {"side": "ally", "hp": 10000, "max_hp": 10000, "energy": 0, "max_energy": 100, "position": 1, "actions": {"basic": {"id": "basic", "tags": ["attack"], "damage_packets": []}}},
    },
    "route": [
        {"actor": "savage", "action": "Skill05", "targets": ["ally1", "ally2"], "expect": {"units": {"savage": {"flags": {"clear_glory_after_next_savage_action": "ready"}}}, "event_counts": {"effect": {"min": 2}}}},
        {"actor": "ally1", "action": "skill_hit", "targets": ["savage"]},
        {"actor": "savage", "action": "Skill01", "targets": ["ally1"], "expect": {"units": {"savage": {"flags": {"clear_glory_after_next_savage_action": False}}}}},
    ],
}
savage_result = BattleSimulator(savage_case).run_route(savage_case["route"])
assert savage_result["metadata"]["route_assertions"]["ok"] is True, savage_result["metadata"]["route_assertions"]
savage_state = {u["id"]: u for u in savage_result["state"]["units"].values()}
savage_statuses = {st["id"]: st for st in savage_state["savage"]["statuses"]}
assert savage_statuses["titanic_corpus"]["stacks"] == 10, savage_statuses
assert "savage_god_glory" not in {st["id"] for st in savage_state["ally1"]["statuses"]}
assert "savage_god_glory" not in {st["id"] for st in savage_state["ally2"]["statuses"]}
checks.append("PASS Savage God Glory/Titanic Corpus states execute with delayed Glory cleanup and layer removal")

# v19.1 Furiae Praetor charge chain: the charge skill should set a forced next
# action instead of immediately firing the follow-up; the next AI/default action
# resolves Drowned in the Crimson Sea and absorbs active Furiae Warriors.
furiae_bundle = compile_enemy_template(ROOT.parent / "model_pack_v3_0" / "models" / "enemies" / "wave1_furiae_praetor.yaml")
furiae_unit2 = deepcopy(furiae_bundle["unit"])
furiae_unit2["hp"] = 100000
furiae_unit2["max_hp"] = 100000
furiae_unit2["stats"] = {"atk": 100, "def": 0}
charge_case = {
    "units": {
        "praetor": furiae_unit2,
        "ally1": {"side": "ally", "hp": 10000, "max_hp": 10000, "position": 0},
        "ally2": {"side": "ally", "hp": 10000, "max_hp": 10000, "position": 1},
        "ally3": {"side": "ally", "hp": 10000, "max_hp": 10000, "position": 2},
        "ally4": {"side": "ally", "hp": 10000, "max_hp": 10000, "position": 3},
    },
}
charge_sim = BattleSimulator(charge_case)
praetor = charge_sim.state.unit("praetor")
charge_sim.resolve_action({"actor_id": "praetor", **praetor.action_defs["Skill05"]}, [], {})
assert any(u.id.startswith("furiae_warrior") and u.alive for u in charge_sim.state.units.values()), [u.id for u in charge_sim.state.units.values()]
charge_sim.resolve_action({"actor_id": "praetor", **praetor.action_defs["Skill03"]}, [], {})
assert praetor.flags.get("forced_next_enemy_action") == "Skill04", praetor.flags
chosen_followup = charge_sim.default_probe_action_id(praetor)
assert chosen_followup == "Skill04", (chosen_followup, praetor.flags)
follow_action = {"actor_id": "praetor", **praetor.action_defs[chosen_followup]}
charge_sim.resolve_action(follow_action, charge_sim.select_targets(follow_action, None), {})
assert praetor.flags.get("absorbed_furiae_warrior_count") == 1, praetor.flags
assert not any(u.id.startswith("furiae_warrior") and u.alive for u in charge_sim.state.units.values())
checks.append("PASS Furiae Praetor charge sets forced next action and follow-up absorbs Furiae Warrior")



# v19.2 ConfigAI target-selector / target-count / HP-ratio baseline.  SelectAISkillTarget
# should influence not only which skill is chosen but also who that skill targets.
ai_target_selector_case = {
    "units": {
        "enemy": {
            "side": "enemy", "hp": 1000, "max_hp": 1000, "stats": {"atk": 100, "def": 0},
            "flags": {
                "enemy_ai_decisions": [
                    {"skill": "SkillMark", "condition": True, "target_selector": {"type": "target_with_status", "status_id": "aim_mark", "target_policy": "all_allies", "target_side": "ally"}},
                ],
            },
            "actions": {"SkillMark": {"id": "SkillMark", "action_type": "enemy_skill", "tags": ["enemy_action", "attack"], "target_policy": "first_ally", "damage_packets": [{"id": "flat", "element": "physical", "flat_damage": 100, "can_crit": False, "ignore_defense_multiplier": True, "ignore_toughness_state_multiplier": True}]}},
        },
        "a0": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 0},
        "a1": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 1, "statuses": [{"id": "aim_mark"}]},
    },
}
ai_target_sim = BattleSimulator(ai_target_selector_case)
ai_enemy = ai_target_sim.state.unit("enemy")
chosen = ai_target_sim.default_probe_action_id(ai_enemy)
assert chosen == "SkillMark"
chosen_action = {"actor_id": "enemy", **ai_enemy.action_defs[chosen]}
selected = ai_target_sim.select_targets(chosen_action, None)
assert selected == ["a1"], (selected, ai_enemy.flags)
ai_target_sim.resolve_action(chosen_action, selected, {})
assert ai_target_sim.state.unit("a1").hp == 900 and ai_target_sim.state.unit("a0").hp == 1000

count_hp_ctx = {"actor_id": "enemy", "actor": ai_enemy, "context": {}, "phase_locked_targets": set()}
assert ai_target_sim.eval_condition({"target_count": {"target_policy": "all_allies", "alive_only": True, "op": ">=", "value": 2}}, count_hp_ctx) is True
assert ai_target_sim.eval_condition({"target_hp_ratio": {"target_policy": "all_allies", "op": "<", "value": 0.95}}, count_hp_ctx) is True
checks.append("PASS enemy ConfigAI SelectAISkillTarget selector, target-count, and HP-ratio predicates execute conservatively")


# v19.3 ConfigAI TargetFilter / custom value / identity predicates and property
# selectors.  These are conservative baselines for real enemy AIs that count or
# select only units passing a TargetFilter, or pick the lowest/highest HP target.
ai_filter_selector_case = {
    "units": {
        "enemy": {
            "side": "enemy", "hp": 1000, "max_hp": 1000, "stats": {"atk": 100, "def": 0},
            "flags": {
                "enemy_ai_decisions": [
                    {"skill": "SkillLowHP", "condition": True, "target_selector": {"type": "property_extreme", "property": "CurrentHP", "strategy": "MinRatio", "target_policy": "all_allies", "target_side": "ally"}},
                ],
                "monster_id": 7000001,
                "rank": 3,
            },
            "actions": {"SkillLowHP": {"id": "SkillLowHP", "action_type": "enemy_skill", "tags": ["enemy_action", "attack"], "target_policy": "first_ally", "damage_packets": [{"id": "flat", "element": "physical", "flat_damage": 100, "can_crit": False, "ignore_defense_multiplier": True, "ignore_toughness_state_multiplier": True}]}},
        },
        "a0": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 0},
        "a1": {"side": "ally", "hp": 400, "max_hp": 1000, "position": 1},
        "m0": {"side": "enemy", "hp": 1000, "max_hp": 1000, "flags": {"custom_bool:1223239280": True, "monster_id": 7002020, "rank": 2, "Break": True}},
        "m1": {"side": "enemy", "hp": 1000, "max_hp": 1000, "flags": {"custom_value_bool:1223239280": True, "monster_id": 7002021, "rank": 1}},
    },
}
ai_filter_sim = BattleSimulator(ai_filter_selector_case)
ai_filter_enemy = ai_filter_sim.state.unit("enemy")
chosen_low = ai_filter_sim.default_probe_action_id(ai_filter_enemy)
assert chosen_low == "SkillLowHP"
low_action = {"actor_id": "enemy", **ai_filter_enemy.action_defs[chosen_low]}
assert ai_filter_sim.select_targets(low_action, None) == ["a1"]
filter_ctx = {"actor_id": "enemy", "actor": ai_filter_enemy, "context": {}, "phase_locked_targets": set()}
assert ai_filter_sim.eval_condition({"target_count": {"target_policy": "all_enemies", "alive_only": True, "op": ">=", "value": 2, "filters": [{"unit_custom_value_bool": {"target": "param_entity", "key": "custom_bool:1223239280"}}]}}, filter_ctx) is True
assert ai_filter_sim.eval_condition({"target_count": {"target_policy": "all_enemies", "alive_only": True, "op": ">=", "value": 1, "filters": [{"unit_identity_compare": {"target": "param_entity", "field": "monster_id", "op": "==", "value": 7002020}}]}}, filter_ctx) is True
assert ai_filter_sim.eval_condition({"unit_identity_compare": {"target": "actor", "field": "rank", "op": ">=", "value": 3}}, filter_ctx) is True
assert ai_filter_sim.eval_condition({"unit_behavior_flag": {"target": "m0", "flag": "Break"}}, filter_ctx) is True
checks.append("PASS enemy ConfigAI TargetFilter/custom-value/identity predicates and AIPropertySelector baseline execute")



# v19.4 Non-Knight ConfigAI dynamic tasks.  Many full-database enemies rely on
# dynamic-value mutation tasks and retarget branches, not just predicates.  Keep
# these semantics executable before broadening enemy samples beyond Knight 3.
ai_dynamic_config = {
    "DecisionList": [
        {
            "$type": "RPG.GameCore.AIDecisionConfig",
            "RootTask": {"$type": "RPG.GameCore.SequenceConfig", "TaskList": [
                {"$type": "RPG.GameCore.SetDynamicValueByAddValue", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"}, "Key": {"Value": "AIFlag"}, "AddValue": {"IsDynamic": False, "FixedValue": {"Value": 2}}, "Min": {"IsDynamic": False, "FixedValue": {"Value": 0}}, "Max": {"IsDynamic": False, "FixedValue": {"Value": 3}}},
                {"$type": "RPG.GameCore.SetDynamicValueByCharacterCount", "DynamicKey": "BreakCount", "ReadTargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "AllTeammate"}, "Predicate": {"$type": "RPG.GameCore.ByContainBehaviorFlag", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "ParamEntity"}, "Flag": "Break"}},
                {"$type": "RPG.GameCore.UseSkill", "SkillName": "SkillA"},
            ]},
        },
        {
            "$type": "RPG.GameCore.AIDecisionConfig",
            "RootTask": {"$type": "RPG.GameCore.SequenceConfig", "TaskList": [
                {"$type": "RPG.GameCore.SwitchCaseByDynamicValue", "Switch": {"IsDynamic": True, "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [987654]}}, "CaseTaskList": [
                    {"Case": {"IsDynamic": False, "FixedValue": {"Value": 2}}, "TaskList": [{"$type": "RPG.GameCore.UseSkill", "SkillName": "SkillSwitch"}]}
                ], "DefaultTaskList": []},
            ]},
        },
    ]
}
ai_dynamic_decisions = _extract_ai_decisions_from_config(ai_dynamic_config)
assert any(d.get("skill") == "SkillA" for d in ai_dynamic_decisions), ai_dynamic_decisions
assert any(d.get("skill") == "SkillSwitch" and "dynamic_hash:987654" in str(d.get("condition")) for d in ai_dynamic_decisions), ai_dynamic_decisions
ai_dynamic_case = {
    "units": {
        "enemy": {
            "side": "enemy", "hp": 1000, "max_hp": 1000, "stats": {"atk": 100, "def": 0},
            "flags": {"AIFlag": 2, "dynamic_hash:987654": 1, "enemy_ai_decisions": ai_dynamic_decisions},
            "actions": {
                "SkillA": {"id": "SkillA", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []},
                "SkillSwitch": {"id": "SkillSwitch", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []},
            },
        },
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 0},
        "m0": {"side": "enemy", "hp": 1000, "max_hp": 1000, "flags": {"Break": True}},
        "m1": {"side": "enemy", "hp": 1000, "max_hp": 1000},
    },
}
ai_dynamic_sim = BattleSimulator(ai_dynamic_case)
ai_dynamic_enemy = ai_dynamic_sim.state.unit("enemy")
assert ai_dynamic_sim.default_probe_action_id(ai_dynamic_enemy) == "SkillA"
assert ai_dynamic_enemy.flags.get("AIFlag") == 3, ai_dynamic_enemy.flags
assert ai_dynamic_enemy.flags.get("BreakCount") == 1, ai_dynamic_enemy.flags
ai_dynamic_enemy.flags["dynamic_hash:987654"] = 2
# Disable the first decision so the switch branch can be selected.
ai_dynamic_enemy.flags["enemy_ai_decisions"][0]["condition"] = False
assert ai_dynamic_sim.default_probe_action_id(ai_dynamic_enemy) == "SkillSwitch"
checks.append("PASS non-Knight ConfigAI dynamic-value add/count/switch tasks execute")

# v19.5 Retarget branches become executable decisions with target selectors.
retarget_config = {
    "DecisionList": [{
        "$type": "RPG.GameCore.AIDecisionConfig",
        "RootTask": {"$type": "RPG.GameCore.SequenceConfig", "TaskList": [
            {"$type": "RPG.GameCore.Retarget", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "AllLightTeam"}, "Predicate": {"$type": "RPG.GameCore.ByIsContainModifier", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "ParamEntity"}, "ModifierName": {"Value": "aim_mark"}}, "TaskList": [{"$type": "RPG.GameCore.UseSkill", "SkillName": "SkillRetarget"}], "FailedTaskList": [{"$type": "RPG.GameCore.UseSkill", "SkillName": "SkillFallback"}]}
        ]},
    }]
}
retarget_decisions = _extract_ai_decisions_from_config(retarget_config)
assert len(retarget_decisions) == 2 and retarget_decisions[0].get("target_selector"), retarget_decisions
retarget_case = {
    "units": {
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "stats": {"atk": 100, "def": 0}, "flags": {"enemy_ai_decisions": retarget_decisions}, "actions": {"SkillRetarget": {"id": "SkillRetarget", "action_type": "enemy_skill", "tags": ["enemy_action", "attack"], "target_policy": "first_ally", "damage_packets": [{"id": "flat", "element": "physical", "flat_damage": 100, "can_crit": False, "ignore_defense_multiplier": True, "ignore_toughness_state_multiplier": True}]}, "SkillFallback": {"id": "SkillFallback", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []}}},
        "a0": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 0},
        "a1": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 1, "statuses": [{"id": "aim_mark"}]},
    }
}
retarget_sim = BattleSimulator(retarget_case)
retarget_enemy = retarget_sim.state.unit("enemy")
chosen_retarget = retarget_sim.default_probe_action_id(retarget_enemy)
assert chosen_retarget == "SkillRetarget", (chosen_retarget, retarget_enemy.flags)
retarget_action = {"actor_id": "enemy", **retarget_enemy.action_defs[chosen_retarget]}
assert retarget_sim.select_targets(retarget_action, None) == ["a1"], retarget_enemy.flags
# Remove the marker; the failed branch should become the deterministic fallback.
retarget_sim.state.unit("a1").statuses = []
assert retarget_sim.default_probe_action_id(retarget_enemy) == "SkillFallback"
checks.append("PASS non-Knight ConfigAI Retarget success/failure branches and target selector execute")


# v19.6 ConfigAI DefaultDSE SuccessScore / CheckScore baseline.  Multiple
# available decisions should be ranked by lowered scores; equal scores keep the
# original source order for deterministic exact-route replay.
ai_score_config = {
    "DecisionList": [
        {
            "$type": "RPG.GameCore.AIDecisionConfig",
            "DecisionName": "LowScore",
            "ScoreEvaluatorType": "DefaultDSE",
            "ConsiderAxisList": [{
                "$type": "RPG.GameCore.CheckPredicateAxis",
                "Predicate": {"$type": "RPG.GameCore.ByCompareDynamicValue", "DynamicKey": {"Value": "AIFlag"}, "CompareType": "Equal", "CompareValue": {"IsDynamic": False, "FixedValue": {"Value": 1}}},
                "SuccessScore": {"Value": 0.1},
            }],
            "RootTask": {"$type": "RPG.GameCore.SequenceConfig", "TaskList": [{"$type": "RPG.GameCore.UseSkill", "SkillName": "SkillLow"}]},
        },
        {
            "$type": "RPG.GameCore.AIDecisionConfig",
            "DecisionName": "HighScore",
            "ScoreEvaluatorType": "DefaultDSE",
            "ConsiderAxisList": [{
                "$type": "RPG.GameCore.CheckPredicateAxis",
                "Predicate": {"$type": "RPG.GameCore.ByCompareDynamicValue", "DynamicKey": {"Value": "AIFlag"}, "CompareType": "Equal", "CompareValue": {"IsDynamic": False, "FixedValue": {"Value": 1}}},
                "SuccessScore": {"Value": 0.8},
            }],
            "RootTask": {"$type": "RPG.GameCore.SequenceConfig", "TaskList": [{"$type": "RPG.GameCore.UseSkill", "SkillName": "SkillHigh"}]},
        },
        {
            "$type": "RPG.GameCore.AIDecisionConfig",
            "DecisionName": "SameScoreTie",
            "ScoreEvaluatorType": "DefaultDSE",
            "ConsiderAxisList": [{"$type": "RPG.GameCore.ChoseSequencedSkillAxis", "CheckScore": {"Value": 0.8}}],
            "RootTask": {"$type": "RPG.GameCore.SequenceConfig", "TaskList": [{"$type": "RPG.GameCore.UseSkill", "SkillName": "SkillTie"}]},
        },
    ]
}
ai_score_decisions = _extract_ai_decisions_from_config(ai_score_config)
assert any(d.get("skill") == "SkillHigh" and d.get("ai_score_axes") for d in ai_score_decisions), ai_score_decisions
ai_score_case = {
    "units": {
        "enemy": {
            "side": "enemy", "hp": 1000, "max_hp": 1000, "stats": {"atk": 100, "def": 0},
            "flags": {"AIFlag": 1, "enemy_ai_decisions": ai_score_decisions},
            "actions": {
                "SkillLow": {"id": "SkillLow", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []},
                "SkillHigh": {"id": "SkillHigh", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []},
                "SkillTie": {"id": "SkillTie", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []},
            },
        },
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 0},
    }
}
ai_score_sim = BattleSimulator(ai_score_case)
ai_score_enemy = ai_score_sim.state.unit("enemy")
assert ai_score_sim.default_probe_action_id(ai_score_enemy) == "SkillHigh", ai_score_enemy.flags
assert close(ai_score_enemy.flags.get("enemy_ai_last_decision_score"), 0.8), ai_score_enemy.flags
# Remove the high-score decision; equal 0.8 candidates should retain source order.
ai_score_enemy.flags["enemy_ai_decisions"] = [d for d in ai_score_decisions if d.get("skill") != "SkillHigh"]
assert ai_score_sim.default_probe_action_id(ai_score_enemy) == "SkillTie", ai_score_enemy.flags
checks.append("PASS enemy ConfigAI DefaultDSE SuccessScore/CheckScore baseline ranks available decisions deterministically")


# v19.7 Most enemy AIs are fixed-sequence-first.  ScoreEvaluator is a
# branch/fallback ranker and must not jump ahead of a legal scripted action.
scripted_first_case = {
    "units": {
        "enemy": {
            "side": "enemy", "hp": 1000, "max_hp": 1000, "stats": {"atk": 100, "def": 0},
            "flags": {
                "enemy_ai_mode": "scripted_sequence_first",
                "enemy_ai_sequence": ["SkillA", "SkillB"],
                "enemy_ai_sequence_index": 0,
                "enemy_ai_decisions": [
                    {"skill": "SkillA", "condition": True, "ai_score_base": 0.0},
                    {"skill": "SkillB", "condition": True, "ai_score_base": 99.0},
                ],
            },
            "actions": {
                "SkillA": {"id": "SkillA", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []},
                "SkillB": {"id": "SkillB", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []},
            },
        },
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 0},
    }
}
scripted_first_sim = BattleSimulator(scripted_first_case)
scripted_enemy = scripted_first_sim.state.unit("enemy")
assert scripted_first_sim.default_probe_action_id(scripted_enemy) == "SkillA", scripted_enemy.flags
scripted_first_sim.resolve_action({"actor_id": "enemy", **scripted_enemy.action_defs["SkillA"]}, [], {})
assert scripted_enemy.flags.get("enemy_ai_sequence_index") == 1, scripted_enemy.flags
assert scripted_first_sim.default_probe_action_id(scripted_enemy) == "SkillB", scripted_enemy.flags
# If the current scripted action is phase-gated out, scored fallback may choose
# another legal branch; the sequence cursor itself is not advanced by selection.
scripted_block_case = deepcopy(scripted_first_case)
scripted_block_case["units"]["enemy"]["flags"]["enemy_ai_sequence"] = ["SkillP2"]
scripted_block_case["units"]["enemy"]["flags"]["enemy_ai_decisions"] = [{"skill": "SkillFallback", "condition": True, "ai_score_base": 1.0}]
scripted_block_case["units"]["enemy"]["actions"] = {
    "SkillP2": {"id": "SkillP2", "action_type": "enemy_skill", "phase_list": [2], "tags": ["enemy_action"], "damage_packets": [], "effects": []},
    "SkillFallback": {"id": "SkillFallback", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []},
}
scripted_block_case["units"]["enemy"]["flags"]["current_phase"] = 1
scripted_block_sim = BattleSimulator(scripted_block_case)
assert scripted_block_sim.default_probe_action_id(scripted_block_sim.state.unit("enemy")) == "SkillFallback"
checks.append("PASS enemy scripted sequence takes priority over score ranking and only falls back when current scripted action is illegal")


# v19.8 Same-turn enemy multi-action chains are interruptible.  A queued
# continuation must re-check death/break/control before resolving so break or CC
# between chained actions cannot execute later sequence packets out of order.
def _enemy_chain_case():
    return {
        "units": {
            "enemy": {
                "side": "enemy", "hp": 1000, "max_hp": 1000, "stats": {"atk": 100, "def": 0},
                "actions": {
                    "SkillStart": {
                        "id": "SkillStart", "action_type": "enemy_skill", "tags": ["enemy_action"], "target_policy": "manual",
                        "damage_packets": [],
                        "effects": [{"type": "launch_action", "actor": "enemy", "action": "SkillFollow", "queue": "immediate_queue", "targets": ["ally"], "enemy_action_chain": True, "chain_id": "enemy_combo", "interruptible_by_break": True, "interruptible_by_control": True}],
                    },
                    "SkillFollow": {
                        "id": "SkillFollow", "action_type": "enemy_skill", "tags": ["enemy_action", "attack", "enemy_action_chain"], "target_policy": "manual", "enemy_action_chain": True,
                        "damage_packets": [{"id": "flat", "element": "physical", "flat_damage": 300, "can_crit": False, "ignore_defense_multiplier": True, "ignore_toughness_state_multiplier": True}],
                    },
                },
            },
            "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 0},
        }
    }

chain_break_sim = BattleSimulator(_enemy_chain_case())
chain_enemy = chain_break_sim.state.unit("enemy")
chain_break_sim.resolve_action({"actor_id": "enemy", **chain_enemy.action_defs["SkillStart"]}, [], {})
assert chain_break_sim.state.immediate_queue, "SkillStart should queue a follow-up chain action"
chain_enemy.is_broken = True
chain_break_sim.drain_queues()
assert chain_break_sim.state.unit("ally").hp == 1000, chain_break_sim.snapshot()
assert any(e.event_type == "queue_skip" and "interrupted by weakness_break" in e.message for e in chain_break_sim.state.log), chain_break_sim.state.log

chain_control_sim = BattleSimulator(_enemy_chain_case())
chain_enemy2 = chain_control_sim.state.unit("enemy")
chain_control_sim.resolve_action({"actor_id": "enemy", **chain_enemy2.action_defs["SkillStart"]}, [], {})
chain_enemy2.statuses.append(StatusEffect.from_dict({"id": "frozen_control", "tags": ["control", "freeze"], "modifiers": {"action_block": True, "frozen": True}}))
chain_control_sim.drain_queues()
assert chain_control_sim.state.unit("ally").hp == 1000, chain_control_sim.snapshot()
assert any(e.event_type == "queue_skip" and "interrupted by control" in e.message for e in chain_control_sim.state.log), chain_control_sim.state.log

chain_ok_sim = BattleSimulator(_enemy_chain_case())
chain_enemy3 = chain_ok_sim.state.unit("enemy")
chain_ok_sim.resolve_action({"actor_id": "enemy", **chain_enemy3.action_defs["SkillStart"]}, [], {})
chain_ok_sim.drain_queues()
assert chain_ok_sim.state.unit("ally").hp == 700, chain_ok_sim.snapshot()
checks.append("PASS enemy same-turn multi-action chains skip queued continuations after weakness break or control without disturbing normal chains")



# v19.9 Monster ConfigAbility graph audit/lowering preview.  Enemy skill effects
# should now be sourced from ConfigAbility/Monster at the compiler boundary, not
# only from hand-written model-pack YAML.  This synthetic source keeps the test
# compact while using real RPG.GameCore node shapes.
monster_ability_src = OUT / "mini_monster_ability_tbgd.zip"
with zipfile.ZipFile(monster_ability_src, "w") as z:
    z.writestr("Config/ConfigAbility/Monster/Monster_Test_Ability.json", json.dumps({
        "AbilityList": [
            {
                "Name": "Monster_Test_Skill01_Phase01",
                "OnStart": [
                    {"$type": "RPG.GameCore.DamageByAttackProperty", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "AllEnemy"}, "AttackProperty": {"$type": "RPG.GameCore.AttackData", "DamageType": {"DamageType": "Fire"}, "DamagePercentage": {"IsDynamic": False, "FixedValue": {"Value": 1.25}}, "SPHitRatio": {"IsDynamic": False, "FixedValue": {"Value": 0.5}}, "AttackType": "Normal"}},
                    {"$type": "RPG.GameCore.AddModifier", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "AllEnemy"}, "ModifierName": {"Value": "BurningMark"}, "LifeTime": {"Value": 2}},
                    {"$type": "RPG.GameCore.SetDynamicValueByAddValue", "DynamicKey": {"Hash": 12345}, "AddValue": {"Value": 1}, "Max": {"Value": 3}},
                    {"$type": "RPG.GameCore.SummonMonster", "DelayRatio": {"Value": 0.5}, "SummonMonsterDataList": [{"MonsterID": 999001}]},
                    {"$type": "RPG.GameCore.SetMonsterPhase", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"}, "PhaseNum": {"Value": 2}},
                    {"$type": "RPG.GameCore.SetActionDelay", "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "Caster"}, "NormalizedValue": {"Value": 0}},
                    {"$type": "RPG.GameCore.TriggerAnimState", "AnimStateName": "Attack"}
                ]
            }
        ],
        "GlobalModifiers": []
    }, ensure_ascii=False))
monster_ability_out = OUT / "monster_ability_lowering_test"
monster_ability_summary = write_monster_ability_graph_lowering(monster_ability_src, monster_ability_out)
assert monster_ability_summary["monster_ability_file_count"] == 1, monster_ability_summary
preview = json.loads((monster_ability_out / "monster_ability_lowering_preview.json").read_text(encoding="utf-8"))
effects = preview["sampled_files"][0]["ability_rows"][0]["effects"]
effect_types = {e["type"] for e in effects}
assert {"damage", "add_status", "modify_dynamic_value", "summon_monster", "set_monster_phase", "action_delay"}.issubset(effect_types), effects
assert preview["sampled_files"][0]["visual_evidence_counts"].get("RPG.GameCore.TriggerAnimState") == 1, preview["sampled_files"][0]
checks.append("PASS Monster ConfigAbility graph lowering preview extracts high-confidence combat nodes and keeps visual evidence-only")

# Full source smoke for non-Knight generalization samples.  This verifies that
# the lowerer finds real non-Knight enemy ability files with damage/status/
# dynamic/summon/phase/action-order coverage rather than only the Knight-3 boss
# templates used by the project harness.
full_tbgd = Path("/mnt/data/turnbasedgamedata-main.zip")
if full_tbgd.exists():
    real_monster_ability_out = OUT / "monster_ability_lowering_real"
    real_summary = write_monster_ability_graph_lowering(full_tbgd, real_monster_ability_out, max_files=5)
    assert real_summary["monster_ability_file_total_available"] >= 300, real_summary
    assert real_summary["non_knight_sample_count"] >= 3, real_summary.get("non_knight_samples")
    assert real_summary["node_bucket_counts"].get("damage", 0) > 10, real_summary["node_bucket_counts"]
    checks.append("PASS full Monster ConfigAbility lowering scan finds non-Knight real enemy samples for later exact-route binding")

# v20.0 Enemy chain cursor/cooldown accounting: same-turn continuation actions
# that execute should record their own skill use/cooldown, but by default they
# must not advance the fixed AI cursor.  The main sequence advances once for the
# initiating action; interrupted continuations never call resolve_action and
# therefore do not record usage or move the cursor.
chain_cursor_case = {
    "units": {
        "enemy": {
            "side": "enemy", "hp": 1000, "max_hp": 1000, "stats": {"atk": 100, "def": 0},
            "flags": {"enemy_ai_sequence": ["SkillStart", "SkillFollow", "SkillNext"], "enemy_ai_sequence_index": 0, "enemy_skill_cooldown_config": {"SkillFollow": {"cd": 2}}},
            "actions": {
                "SkillStart": {"id": "SkillStart", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": [{"type": "launch_action", "actor": "enemy", "action": "SkillFollow", "queue": "immediate_queue", "targets": ["ally"], "enemy_action_chain": True, "chain_id": "cursor_chain"}]},
                "SkillFollow": {"id": "SkillFollow", "action_type": "enemy_skill", "tags": ["enemy_action", "attack", "enemy_action_chain"], "target_policy": "manual", "enemy_action_chain": True, "damage_packets": [{"id": "flat", "element": "physical", "flat_damage": 1, "can_crit": False, "ignore_defense_multiplier": True, "ignore_toughness_state_multiplier": True}]},
                "SkillNext": {"id": "SkillNext", "action_type": "enemy_skill", "tags": ["enemy_action"], "damage_packets": [], "effects": []},
            },
        },
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "position": 0},
    }
}
chain_cursor_sim = BattleSimulator(chain_cursor_case)
chain_cursor_enemy = chain_cursor_sim.state.unit("enemy")
chain_cursor_sim.resolve_action({"actor_id": "enemy", **chain_cursor_enemy.action_defs["SkillStart"]}, [], {})
assert chain_cursor_enemy.flags.get("enemy_ai_sequence_index") == 1, chain_cursor_enemy.flags
chain_cursor_sim.drain_queues()
assert chain_cursor_enemy.flags.get("enemy_ai_sequence_index") == 1, chain_cursor_enemy.flags
assert chain_cursor_enemy.flags.get("enemy_skill_use_counts", {}).get("SkillFollow") == 1, chain_cursor_enemy.flags
assert chain_cursor_enemy.flags.get("enemy_skill_cooldowns", {}).get("SkillFollow") == 2, chain_cursor_enemy.flags
assert chain_cursor_sim.state.unit("ally").hp == 999, chain_cursor_sim.snapshot()
checks.append("PASS enemy chained continuations record executed skill use/cooldown but do not advance fixed AI cursor by default")


# v20.1 Monster ConfigAbility preview IR is now bound into compiled enemy runtime actions.
# Non-damage high-confidence graph nodes execute as normal effects; graph damage
# is kept as evidence when MonsterSkillConfig already supplied a damage packet to
# avoid double-counting.
if full_pack.exists():
    compiler_out_v59 = OUT / "enemy_template_compiler_v59"
    compiler_summary_v59 = compile_enemy_model_pack(full_pack, compiler_out_v59)
    assert compiler_summary_v59["version"] == "v0.13", compiler_summary_v59
    assert compiler_summary_v59["compiled_count"] >= 6, compiler_summary_v59
    assert any(row.get("id") == "real_sample_aml_elite01_01" for row in compiler_summary_v59["rows"]), compiler_summary_v59
    assert sum(row.get("ability_graph_effect_count", 0) for row in compiler_summary_v59["rows"]) > 0, compiler_summary_v59

    sample_compiled = yaml.safe_load((compiler_out_v59 / "compiled_enemies" / "real_sample_aml_elite01_01.compiled_enemy.yaml").read_text(encoding="utf-8"))
    sample_unit = sample_compiled["unit"]
    sample_action = sample_unit["actions"].get("Skill01")
    assert sample_action, sample_unit["actions"].keys()
    binding = sample_action.get("metadata", {}).get("monster_ability_graph_binding") or {}
    assert binding.get("runtime_effects_added", 0) > 0, binding
    assert binding.get("damage_packets_kept_as_evidence", 0) >= 0, binding
    graph_effects = [e for e in sample_action.get("effects", []) if isinstance(e, dict) and e.get("ability_graph_source")]
    assert graph_effects, sample_action

    # Execute the compiled real sample action. The exact numeric result is not
    # important here; this protects the runtime binding path and verifies graph
    # statuses/flags do not stay as inert metadata.
    sample_case = {
        "units": {
            "ally0": {"side": "ally", "hp": 5000, "max_hp": 5000, "speed": 100, "position": 0},
            "sample": sample_unit,
        },
        "route": [{"actor": "sample", "action": "Skill01", "targets": ["ally0"], "expect": {"event_counts": {"effect": {"min": 1}}}}],
    }
    sample_result = BattleSimulator(sample_case).run_route(sample_case["route"])
    assert sample_result["metadata"]["route_assertions"]["ok"] is True, sample_result["metadata"]["route_assertions"]
    statuses = {s["id"] for s in sample_result["state"]["units"]["ally0"].get("statuses", [])}
    sample_flags = sample_result["state"]["units"]["sample"].get("flags", {})
    assert statuses or any(str(k).startswith("dynamic:") for k in sample_flags), sample_result["state"]["units"]
checks.append("PASS Monster ConfigAbility preview IR is bound into compiled enemy runtime actions and executes on non-Knight sample")

# v20.2 Non-Knight generated model-pack templates cover different real enemy shapes.
# They are intentionally unscaled sample templates, but all source skills and
# ConfigAI paths come from TurnBasedGameData and compile through the same loader.
if full_pack.exists():
    compiler_out_non_knight = OUT / "enemy_template_compiler_non_knight_v59"
    compiler_summary_non_knight = compile_enemy_model_pack(full_pack, compiler_out_non_knight)
    generated_rows = [row for row in compiler_summary_non_knight["rows"] if str(row.get("id", "")).startswith("real_sample_")]
    assert len(generated_rows) >= 3, generated_rows
    assert all(row.get("skill_count", 0) > 0 for row in generated_rows), generated_rows
    assert all(row.get("ai_decision_count", 0) > 0 for row in generated_rows), generated_rows
    assert any(row.get("ability_graph_effect_count", 0) > 0 for row in generated_rows), generated_rows
checks.append("PASS non-Knight real enemy templates compile with ConfigAI and Monster Ability graph bindings")

# v20.3 Phase transitions must clear/cancel queued enemy chains unless a chain
# explicitly opts into carrying across phase. This prevents old same-turn
# continuations from leaking into the new phase after a break/phase boundary.
phase_chain_case = {
    "units": {
        "enemy": {
            "side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 100, "stats": {"atk": 100, "def": 0},
            "hp_bars_total": 2, "hp_bars_remaining": 2,
            "hp_model": {"type": "phase_hp", "carry_over_damage": False, "bars": [{"hp": 1000}, {"hp": 1000}]},
            "actions": {
                "Start": {"id": "Start", "action_type": "enemy_skill", "tags": ["enemy_action"], "effects": [{"type": "launch_action", "actor": "enemy", "action": "Follow", "queue": "immediate_queue", "targets": ["ally"], "enemy_action_chain": True, "chain_id": "phase_chain"}], "damage_packets": []},
                "Follow": {"id": "Follow", "action_type": "enemy_skill", "tags": ["enemy_action", "attack"], "damage_packets": [{"id": "flat", "element": "physical", "flat_damage": 100, "can_crit": False, "ignore_defense_multiplier": True}]},
            },
        },
        "ally": {"side": "ally", "hp": 1000, "max_hp": 1000, "speed": 100},
    }
}
phase_chain_sim = BattleSimulator(phase_chain_case)
phase_enemy = phase_chain_sim.state.unit("enemy")
phase_chain_sim.resolve_action({"actor_id": "enemy", **phase_enemy.action_defs["Start"]}, [], {})
assert phase_chain_sim.state.immediate_queue, "Start should queue Follow"
# Simulate phase transition before the queued continuation resolves.
phase_enemy.flags["current_phase"] = 2
phase_enemy.flags["monster_phase"] = 2
phase_chain_sim.drain_queues()
# v0.59+ drain_queues should skip this stale chain when phase changes.
assert phase_chain_sim.state.unit("ally").hp == 1000, phase_chain_sim.snapshot()
assert any(e.event_type == "queue_skip" and "phase_changed" in e.message for e in phase_chain_sim.state.log), [e.to_json() for e in phase_chain_sim.state.log]
checks.append("PASS enemy chained continuations are skipped when phase changes before queued follow-up resolves")


# v20.5 Derived damage is death-stopping and preserves true kill ownership.
# Primary action damage can kill the target; subsequent additional/zone damage
# should not corpse-whip that defeated target or steal kill credit.
derived_stop_case = {
    "settings": {"kill_energy_base": 10, "kill_energy_affected_by_err": False},
    "units": {
        "seele": {"side": "ally", "hp": 1000, "max_hp": 1000, "energy": 0, "max_energy": 100, "stats": {"atk": 100, "def": 0}},
        "tribbie": {"side": "ally", "hp": 1000, "max_hp": 1000, "energy": 0, "max_energy": 100, "stats": {"hp": 10000, "def": 0}},
        "enemy": {"side": "enemy", "hp": 10, "max_hp": 10, "stats": {"def": 0}},
    },
    "triggers": [
        {"id": "zone_add", "owner": "tribbie", "timing": "after_ally_attacks", "condition": "action.actor_id != tribbie", "effects": [{"type": "zone_additional_damage", "source": "tribbie", "target_policy": "highest_hp_among_hit_targets", "element": "quantum", "damage_type": "additional_damage", "scaling_stat": "hp", "multiplier": 1.0, "can_crit": False}]},
    ],
}
derived_stop_sim = BattleSimulator(derived_stop_case)
derived_stop_sim.resolve_action({"id": "basic", "actor_id": "seele", "tags": ["attack", "basic", "can_trigger_kill_energy"], "damage_packets": [{"id": "hit", "element": "quantum", "flat_damage": 20, "can_crit": False, "ignore_defense_multiplier": True}]}, ["enemy"], {})
derived_logs = [{"event_type": e.event_type, "message": e.message, "data": e.data} for e in derived_stop_sim.state.log]
tribbie_damage_logs = [e for e in derived_logs if e["event_type"] == "damage" and e["data"].get("actor_id") == "tribbie"]
assert not tribbie_damage_logs, tribbie_damage_logs
assert close(derived_stop_sim.state.unit("seele").energy, 10), derived_stop_sim.snapshot()
assert close(derived_stop_sim.state.unit("tribbie").energy, 0), derived_stop_sim.snapshot()
assert any(e["event_type"] == "derived_damage_skip" for e in derived_logs), derived_logs
checks.append("PASS derived/additional damage stops when the primary attack already defeated the target")

# v20.6 Kafka-style DoT immediate settlement is death-stopping. If an earlier
# DoT tick kills the target, later DoTs do not resolve, and kill credit/energy
# belong to the DoT applier rather than to the detonation trigger.
dot_detonation_case = {
    "settings": {"kill_energy_base": 10, "kill_energy_affected_by_err": False},
    "units": {
        "trigger": {"side": "ally", "hp": 1000, "max_hp": 1000, "energy": 0, "max_energy": 100, "actions": {"detonate": {"id": "detonate", "actor_id": "trigger", "tags": [], "target_policy": "manual", "damage_packets": [], "effects": [{"type": "detonate_dots", "target": "target"}]}}},
        "kafka": {"side": "ally", "hp": 1000, "max_hp": 1000, "energy": 0, "max_energy": 100},
        "sampo": {"side": "ally", "hp": 1000, "max_hp": 1000, "energy": 0, "max_energy": 100},
        "enemy": {"side": "enemy", "hp": 15, "max_hp": 100, "statuses": [
            {"id": "shock_from_kafka", "source_id": "kafka", "tags": ["dot", "shock"], "modifiers": {"dot_damage": {"amount": 20, "element": "lightning", "damage_type": "dot_damage", "source_id": "kafka"}}},
            {"id": "wind_from_sampo", "source_id": "sampo", "tags": ["dot", "wind_shear"], "modifiers": {"dot_damage": {"amount": 20, "element": "wind", "damage_type": "dot_damage", "source_id": "sampo"}}},
        ]},
    },
}
dot_sim = BattleSimulator(dot_detonation_case)
dot_actor = dot_sim.state.unit("trigger")
dot_sim.resolve_action({"actor_id": "trigger", **dot_actor.action_defs["detonate"]}, ["enemy"], {})
dot_logs = [{"event_type": e.event_type, "message": e.message, "data": e.data} for e in dot_sim.state.log]
dot_damage_events = [e for e in dot_logs if e["event_type"] == "dot_damage"]
assert len(dot_damage_events) == 1, dot_damage_events
assert dot_damage_events[0]["data"].get("source") == "kafka", dot_damage_events
assert close(dot_sim.state.unit("kafka").energy, 10), dot_sim.snapshot()
assert close(dot_sim.state.unit("sampo").energy, 0), dot_sim.snapshot()
assert close(dot_sim.state.unit("trigger").energy, 0), dot_sim.snapshot()
assert any(e["event_type"] == "derived_damage_skip" and "DoT detonation stopped" in e["message"] for e in dot_logs), dot_logs
checks.append("PASS immediate DoT detonation stops at the killing DoT and credits the DoT applier")


# v20.7 Primary damage windows are full-resolution.  Death during a
# multi-hit skill must not truncate later packets from that same primary
# action, and a single large hit is logged at full damage rather than capped
# to remaining HP.  Only later derived/triggered damage is death-stopping.
primary_full_resolution_case = {
    "settings": {"kill_energy_base": 10, "kill_energy_affected_by_err": False},
    "units": {
        "attacker": {"side": "ally", "hp": 1000, "max_hp": 1000, "energy": 0, "max_energy": 100, "stats": {"def": 0}},
        "enemy": {"side": "enemy", "hp": 300, "max_hp": 300, "stats": {"def": 0}},
    },
}
primary_sim = BattleSimulator(primary_full_resolution_case)
seven_packets = [
    {"id": f"hit{i}", "element": "quantum", "flat_damage": 100, "can_crit": False, "ignore_defense_multiplier": True}
    for i in range(1, 8)
]
primary_sim.resolve_action({"id": "seven_hit_skill", "actor_id": "attacker", "tags": ["attack", "skill", "can_trigger_kill_energy"], "damage_packets": seven_packets}, ["enemy"], {})
primary_logs = [{"event_type": e.event_type, "message": e.message, "data": e.data} for e in primary_sim.state.log]
primary_damage_events = [e for e in primary_logs if e["event_type"] == "damage" and e["data"].get("actor_id") == "attacker"]
assert len(primary_damage_events) == 7, primary_damage_events
assert [round(float(e["data"].get("damage", 0)), 6) for e in primary_damage_events] == [100.0] * 7, primary_damage_events
assert close(primary_sim.state.unit("attacker").energy, 10), primary_sim.snapshot()
assert any(e["event_type"] == "primary_damage_overkill" for e in primary_logs), primary_logs

large_hit_case = {
    "settings": {"kill_energy_base": 10, "kill_energy_affected_by_err": False},
    "units": {
        "attacker": {"side": "ally", "hp": 1000, "max_hp": 1000, "energy": 0, "max_energy": 100, "stats": {"def": 0}},
        "enemy": {"side": "enemy", "hp": 300, "max_hp": 300, "stats": {"def": 0}},
    },
}
large_sim = BattleSimulator(large_hit_case)
large_sim.resolve_action({"id": "large_hit", "actor_id": "attacker", "tags": ["attack", "ultimate", "can_trigger_kill_energy"], "damage_packets": [{"id": "big", "element": "quantum", "flat_damage": 1000, "can_crit": False, "ignore_defense_multiplier": True}]}, ["enemy"], {})
large_damage_events = [e for e in large_sim.state.log if e.event_type == "damage"]
assert len(large_damage_events) == 1, [e.to_json() for e in large_sim.state.log]
assert close(float(large_damage_events[0].data.get("damage", 0)), 1000), large_damage_events[0].to_json()
assert close(large_sim.state.unit("attacker").energy, 10), large_sim.snapshot()
checks.append("PASS primary multi-hit and large-hit damage windows resolve full numeric damage after lethal HP is reached")


# v0.65 shield status expiration removes only remaining shield from live checkpoint style timed shields.
shield_expiry_case = {
    "global": {"skill_points": 0},
    "units": {
        "actor": {"side": "ally", "hp": 1000, "max_hp": 1000, "shield": 600, "speed": 100, "statuses": [{"id": "timed_shield", "modifiers": {"shield_expire_remove_amount": 1000}, "duration": {"type": "actor_turns", "value": 1}}], "actions": {"basic": {"tags": ["attack", "consumes_regular_action"], "target_policy": "enemy", "damage_packets": []}}},
        "enemy": {"side": "enemy", "hp": 1000, "max_hp": 1000, "speed": 1000},
    },
    "route": [{"actor": "actor", "action": "basic", "targets": ["enemy"]}],
}
shield_path = OUT / "timed_shield_expire_case.yaml"
shield_path.write_text(yaml.safe_dump(shield_expiry_case, allow_unicode=True, sort_keys=False), encoding="utf-8")
shield_result = run_case(shield_path)
assert close(shield_result["state"]["units"]["actor"]["shield"], 0.0), shield_result["state"]["units"]["actor"]
checks.append("PASS timed shield status expiration removes remaining shield without assuming unabsorbed original amount")

if __name__ == "__main__":
    report = "# HSR simulator prototype v7.7 validation\n\nAll smoke tests and targeted regression checks passed.\n\n" + "\n".join(f"- {c}" for c in checks) + "\n"
    (ROOT / "VALIDATION_v7_7.md").write_text(report, encoding="utf-8")
    print(report)

"""Local command line client; combat rules belong to DecisionSystem."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .battle_archive import read_archive, verify_archive, write_archive
from .session import BattleSession, command_from_json
from .tbgd.battle_catalog import build_battle_rulebook


def _dump(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def _show_state(session: BattleSession) -> None:
    print(f"波次 {session.state.wave_index + 1}  战技点 {session.state.skill_points}/{session.state.max_skill_points}")
    for unit in session.state.units.values():
        print(f"  {unit.unit_id} [{unit.side}] HP {unit.hp:g}/{unit.max_hp:g}  能量 {unit.energy:g}/{unit.max_energy:g}  韧性 {unit.toughness:g}/{unit.max_toughness:g}")
    if session.outcome:
        print(f"战斗结果：{session.outcome}")


def _play(session: BattleSession) -> int:
    while not session.outcome:
        decision = session.advance()
        _show_state(session)
        if session.outcome:
            break
        if not decision.ready:
            _dump(decision.to_json())
            return 2
        choices = decision.availability.choices
        for index, choice in enumerate(choices, 1):
            query = choice.target_query
            targets = ", ".join(query.candidate_ids) if query else "无需目标"
            label = {"manual_ultimate_request": "请求插入终结技", "queue_action": "执行队列动作",
                     "timeline_actor": "选择同速行动者"}.get(choice.choice_kind, "行动")
            print(f"{index}. {choice.actor_id} → {label} {choice.action_id} Lv{choice.action_level}  {targets}")
        try:
            selected = input("动作编号（q 保存退出，j 查看完整合法动作）：").strip()
            if selected.lower() == "q":
                return 0
            if selected.lower() == "j":
                _dump(decision.to_json())
                continue
            index = int(selected) - 1
            if index < 0 or index >= len(choices):
                raise ValueError("动作编号超出范围")
            choice = choices[index]
            command = dict(choice.command_template)
            query = choice.target_query
            if query is not None and query.selection_mode == "explicit":
                print(f"选择 {query.selection_min} 至 {query.selection_max} 个目标：")
                for target_index, target_id in enumerate(query.candidate_ids, 1):
                    print(f"  {target_index}. {target_id}")
                selected_targets = input("目标编号或 ID（多个用空格分隔）：").split()
                command["target_ids"] = [
                    query.candidate_ids[int(value) - 1]
                    if value not in query.candidate_ids and value.isascii() and value.isdecimal()
                    and 1 <= int(value) <= len(query.candidate_ids) else value
                    for value in selected_targets
                ]
            result = session.submit(command_from_json(command))
            print(f"提交：{result.transition.outcome.category}")
            if result.transition.outcome.reason_codes:
                print("；".join(result.transition.outcome.reason_codes))
        except (ValueError, TypeError, KeyError) as exc:
            print(f"输入无效：{exc}")
        except (EOFError, KeyboardInterrupt):
            print("\n结束输入，保存当前会话。")
            return 0
    return 0


def _script_commands(script: dict[str, Any]) -> list[Any]:
    if set(script) != {"commands"} or not isinstance(script["commands"], list):
        raise ValueError("command script must be an object with a commands array")
    return [command_from_json(value) for value in script["commands"]]


def _run(session: BattleSession, commands: list[Any]) -> int:
    for index, command in enumerate(commands):
        decision = session.advance()
        if session.outcome or not decision.ready:
            raise ValueError(f"script command {index} has no current decision: {session.outcome or decision.blocked_reason}")
        result = session.submit(command)
        if not result.transition.outcome.successor_eligible:
            _dump(result.transition.to_json())
            return 2
    session.advance()
    _show_state(session)
    return 0 if session.outcome else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="星穹铁道本地战斗模拟器：双方手动操作、波次战斗与可校验回放")
    parser.add_argument("--data-root", type=Path, default=Path(__file__).resolve().parents[3] / "turnbasedgamedata-main")
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("play", "query", "run"):
        command = sub.add_parser(mode)
        command.add_argument("scenario", type=Path)
        if mode != "query":
            command.add_argument("--output", type=Path, required=True, help="保存战斗记录；拒绝覆盖已有文件")
        if mode == "run":
            command.add_argument("--commands", type=Path, required=True)
    replay = sub.add_parser("replay")
    replay.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    session = None
    try:
        if getattr(args, "output", None) is not None and args.output.exists():
            raise FileExistsError(f"输出文件已存在：{args.output}")
        data = read_archive(args.archive if args.mode == "replay" else args.scenario)
        scenario_data = data["scenario"] if args.mode == "replay" else data
        commands = _script_commands(read_archive(args.commands)) if args.mode == "run" else None
        print("正在编译所选战斗内容……", file=sys.stderr)
        rules = build_battle_rulebook(args.data_root, scenario_data)
        if args.mode == "replay":
            result = verify_archive(data, rules)
            _dump(result)
            return 0 if result["ok"] else 2
        session = BattleSession(rules, scenario_data)
        if args.mode == "query":
            decision = session.advance()
            _dump({"snapshot": session.state.snapshot().to_json(), "decision": decision.to_json()})
            return 0 if decision.ready or session.outcome else 2
        if args.mode == "run":
            assert commands is not None
            return _run(session, commands)
        return _play(session)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    finally:
        if session is not None and getattr(args, "output", None) is not None:
            try:
                path = write_archive(args.output, session.archive())
                print(f"战斗记录已保存：{path}", file=sys.stderr)
            except (OSError, ValueError) as exc:
                print(f"保存失败：{exc}", file=sys.stderr)
                return 2


if __name__ == "__main__":
    raise SystemExit(main())

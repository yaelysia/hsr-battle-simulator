"""Phase 4: DoT泛化 + SuperBreak 集成验证。"""
import sys, json, os

sys.path.insert(0, '.')
from hsr_simulator_prototype_v7_7 import BattleSimulator, load_case

def get_trace(result):
    return result.get("metadata", {}).get("route_action_trace", [])

def test_super_break_case():
    print("=== 测试: super_break_case ===")
    case = load_case('examples/super_break_case.yaml')
    sim = BattleSimulator(case)
    result = sim.run_route(case.get('route', []))
    
    trace = get_trace(result)
    print(f"  Trace entries: {len(trace)}")
    
    sb_records = []
    break_records = []
    toughness_records = []
    dot_records = []
    
    for entry in trace:
        sett = entry.get("settlement", {})
        sb_records.extend(sett.get("super_break_records", []))
        break_records.extend(sett.get("break_records", []))
        toughness_records.extend(sett.get("toughness_records", []))
        dot_records.extend(sett.get("dot_records", []))
    
    print(f"  super_break_records: {len(sb_records)}")
    print(f"  break_records:       {len(break_records)}")
    print(f"  toughness_records:   {len(toughness_records)}")
    print(f"  dot_records:         {len(dot_records)}")
    
    errors = []
    
    # 验证超击破记录
    if len(sb_records) < 1:
        errors.append("没有 super_break_records")
    else:
        for sr in sb_records:
            print(f"  SuperBreak: element={sr.get('element')} base={sr.get('base_damage',0):.1f} "
                  f"toughness_mult={sr.get('toughness_mult',0):.3f} final={sr.get('final_damage',0):.1f} "
                  f"hp_loss={sr.get('hp_loss',0):.1f}")
            if sr.get('final_damage', 0) <= 0:
                errors.append("超击破伤害为 0")
    
    # 验证击破记录
    if len(break_records) < 1:
        errors.append("没有 break_records")
    
    # 验证 after snapshot 中 is_broken
    for entry in trace:
        after = entry.get("after", {})
        for enemy in after.get("enemies", []):
            if enemy.get("id") == "target":
                ib = enemy.get("is_broken")
                print(f"  after.target: is_broken={ib} toughness={enemy.get('toughness')}")
    
    if errors:
        print("\n  FAILURES:")
        for e in errors:
            print(f"    - {e}")
    else:
        print("  [PASS] 超击破记录全部到位")
    return len(errors) == 0

def test_all_regression():
    print("\n=== 回归测试 ===")
    example_dir = 'examples'
    cases = sorted([f for f in os.listdir(example_dir) if f.endswith(('.yaml', '.yml'))])
    failed = []
    for case_file in cases:
        path = os.path.join(example_dir, case_file)
        try:
            case = load_case(path)
            sim = BattleSimulator(case)
            sim.run_route(case.get('route', []))
        except Exception as e:
            failed.append(f"{case_file}: {e}")
    if failed:
        print("  FAILURES:")
        for f in failed:
            print(f"    - {f}")
    else:
        print(f"  All {len(cases)} examples PASS")
    return len(failed) == 0

if __name__ == '__main__':
    ok = test_super_break_case()
    ok = test_all_regression() and ok
    sys.exit(0 if ok else 1)

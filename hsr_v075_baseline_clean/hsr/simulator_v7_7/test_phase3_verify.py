"""Phase 3: 击破/DoT 集成验证脚本 (v2)。"""
import sys, json, os

sys.path.insert(0, '.')
from hsr_simulator_prototype_v7_7 import BattleSimulator, load_case

def get_trace(result):
    return result.get("metadata", {}).get("route_action_trace", [])

def test_break_case():
    print("=== 测试: break_dot_minimal_case ===")
    case = load_case('examples/break_dot_minimal_case.yaml')
    sim = BattleSimulator(case)
    result = sim.run_route(case.get('route', []))
    
    trace = get_trace(result)
    print(f"  Trace entries: {len(trace)}")
    
    break_records = []
    toughness_records = []
    dot_records = []
    status_records = []
    
    for entry in trace:
        sett = entry.get("settlement", {})
        break_records.extend(sett.get("break_records", []))
        toughness_records.extend(sett.get("toughness_records", []))
        dot_records.extend(sett.get("dot_records", []))
        status_records.extend(sett.get("status_records", []))
    
    print(f"  break_records:     {len(break_records)}")
    print(f"  toughness_records: {len(toughness_records)}")
    print(f"  dot_records:       {len(dot_records)}")
    print(f"  status_records:    {len(status_records)}")
    
    errors = []
    
    if len(break_records) < 1:
        errors.append("没有 break_records")
    else:
        br = break_records[0]
        print(f"  Break: element={br.get('element')} base={br.get('base_break_damage',0):.1f} final={br.get('final_break_damage',0):.1f} hp_loss={br.get('hp_loss',0):.1f}")
    
    if len(toughness_records) < 1:
        errors.append("没有 toughness_records")
    else:
        breaks_ct = sum(1 for t in toughness_records if t.get('is_break'))
        nobreak_ct = len(toughness_records) - breaks_ct
        print(f"  Toughness: {nobreak_ct} non-break + {breaks_ct} break")
    
    if len(dot_records) < 1:
        errors.append("没有 dot_records")
    else:
        for dr in dot_records:
            print(f"  DoT: kind={dr.get('kind')} base={dr.get('base_damage',0):.1f} final={dr.get('final_damage',0):.1f} hp_loss={dr.get('hp_loss',0):.1f}")
    
    aftermath = [s for s in status_records if s.get('status_type') == 'break_aftermath']
    print(f"  Aftermath statuses: {len(aftermath)}")
    
    if errors:
        print("\n  FAILURES:")
        for e in errors:
            print(f"    - {e}")
    else:
        print("  [PASS] 击破记录全部到位")
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
    ok = test_break_case() 
    ok = test_all_regression() and ok  # explicit regression
    sys.exit(0 if ok else 1)

#!/usr/bin/env python3
"""Phase 2.5 结算验证 UI —— 零依赖，生成自包含 HTML 并用浏览器打开。

用法：
    python validate_ui.py <case.yaml> [--tbgd <tbgd_dir>] [--steps N]

示例：
    python validate_ui.py examples/conditional_modifier_case.yaml
    python validate_ui.py ../model_pack_v3_0/compiled_cases/arbitration_4_3_knight_3_live_c0_to_c8_simulator_only.yaml --tbgd ../../../turnbasedgamedata-main/turnbasedgamedata-main --steps 10
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from hsr_simulator_prototype_v7_7 import BattleSimulator, load_case
from hsr_engine.tbgd_loader import TBGDSource


# ── HTML 模板 ──────────────────────────────────────────────────────────────

HTML_CSS = r"""
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;height:100vh;overflow:hidden}
#sidebar{width:260px;min-width:260px;background:#161b22;border-right:1px solid #30363d;overflow-y:auto;padding:8px}
#main{flex:1;overflow-y:auto;padding:16px 24px}
h2{color:#58a6ff;margin-bottom:8px;font-size:15px}
.header-bar{background:#161b22;padding:12px 24px;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:16px;flex-shrink:0}
.header-bar .title{font-size:16px;font-weight:600;color:#f0f6fc}
.header-bar .meta{font-size:12px;color:#8b949e}
.step-btn{display:block;width:100%;text-align:left;padding:6px 10px;margin:2px 0;border:1px solid #30363d;border-radius:6px;background:#0d1117;color:#c9d1d9;cursor:pointer;font-size:12px;transition:.15s}
.step-btn:hover{background:#1f2937;border-color:#58a6ff}
.step-btn.active{background:#1f6feb22;border-color:#58a6ff;color:#58a6ff}
.rec-card{margin:6px 0;padding:10px 14px;border-radius:8px;border:1px solid #30363d;background:#161b22;font-size:13px}
.rec-card h3{font-size:13px;margin-bottom:6px;display:flex;align-items:center;gap:6px}
.rec-card .kv{display:grid;grid-template-columns:180px 1fr;gap:2px 8px;font-size:12px}
.rec-card .kv .k{color:#8b949e;text-align:right}
.rec-card .kv .v{color:#c9d1d9;word-break:break-all}
.rec-card .cn{background:#1f6feb22;color:#58a6ff;padding:0 4px;border-radius:3px;font-weight:500}
.rec-card .nocn{color:#484f58;font-style:italic}
.tab-bar{display:flex;gap:4px;margin-bottom:12px;flex-wrap:wrap}
.tab-btn{padding:4px 12px;border:1px solid #30363d;border-radius:6px;background:#0d1117;color:#8b949e;cursor:pointer;font-size:12px;transition:.15s}
.tab-btn:hover{color:#c9d1d9;border-color:#58a6ff}
.tab-btn.active{background:#1f6feb33;color:#58a6ff;border-color:#58a6ff}
.badge{display:inline-block;padding:1px 6px;border-radius:10px;font-size:10px;margin-left:4px}
.badge-buff{background:#23863622;color:#3fb950}
.badge-debuff{background:#da363322;color:#f85149}
.badge-other{background:#8b949e22;color:#8b949e}
.empty-hint{color:#484f58;font-size:13px;padding:20px;text-align:center}
details{margin:4px 0}
summary{color:#58a6ff;cursor:pointer;font-size:12px}
summary:hover{color:#79c0ff}
.scene-unit{border:1px solid #30363d;border-radius:8px;padding:12px;margin:8px 0;background:#161b22}
.scene-unit h4{color:#f0f6fc;margin-bottom:6px}
.scene-status{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;margin:2px;border-radius:12px;background:#1f2937;font-size:11px}
</style>
"""

HTML_JS = r"""
let currentStep=-1,currentTab='all';

function $(id){return document.getElementById(id)}

function renderSidebar(){
  let html='';
  allSteps.forEach((s,i)=>{
    let label=s.step_label||('Step '+i);
    let cls=i===currentStep?'step-btn active':'step-btn';
    html+=`<button class="${cls}" onclick="selectStep(${i})">${esc(label)}</button>`;
  });
  $('sidebar').innerHTML=html;
}

function selectStep(i){
  currentStep=i;
  renderSidebar();
  renderMain();
}

function selectTab(tab){
  currentTab=tab;
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  renderMain();
}

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

function kv(k,v,cn){
  let vhtml=esc(v);
  if(v===null||v===undefined||v==='')vhtml='<span class="nocn">—</span>';
  if(cn)vhtml+=` <span class="cn">${esc(cn)}</span>`;
  return `<div class="kv"><span class="k">${esc(k)}</span><span class="v">${vhtml}</span></div>`;
}

function statusCard(r){
  let cn=r.status_name_cn||'';
  let tp=r.status_type||'';
  let badge='';
  if(tp==='Buff')badge='<span class="badge badge-buff">Buff</span>';
  else if(tp==='Debuff')badge='<span class="badge badge-debuff">Debuff</span>';
  let cnSpan=cn?`<span class="cn">${esc(cn)}</span>`:'<span class="nocn">(无中文名)</span>';
  return `<div class="rec-card">
    <h3>📌 状态 ${cnSpan}${badge}</h3>
    ${kv('status_id',r.status_id)}${kv('变化类型',r.change_type)}${kv('目标',r.unit_id)}
    ${kv('来源',r.source_id)}${kv('层数',`${r.old_stacks} → ${r.new_stacks}`)}
    ${kv('最大层数',r.max_stacks)}${kv('持续类型',r.duration_type)}${kv('持续值',r.duration_value)}
    ${kv('原因',r.reason)}
  </div>`;
}

function damageCard(r){
  let el=r.element||'';
  return `<div class="rec-card">
    <h3>💥 伤害 <span class="cn">${esc(el)}</span> ${r.crit?'<span class="badge badge-debuff">暴击</span>':''} ${r.is_overkill?'<span class="badge badge-other">过量</span>':''}</h3>
    ${kv('来源',r.actor_id)}${kv('目标',r.target_id)}${kv('元素',r.element)}
    ${kv('基础伤害',r.base_damage)}${kv('最终伤害',r.final_damage)}${kv('应用伤害',r.damage_applied)}
    ${kv('护盾吸收',r.shield_absorbed)}${kv('HP损失',r.hp_loss)}${kv('过量',r.overkill)}
    ${kv('暴击倍率',r.crit_dmg_mult)}${kv('增伤倍率',r.dmg_bonus_mult)}
    ${kv('防御倍率',r.def_mult)}${kv('抗性倍率',r.res_mult)}
    ${kv('受伤倍率',r.dmg_taken_mult)}${kv('韧性倍率',r.toughness_mult)}
  </div>`;
}

function spCard(r){
  return `<div class="rec-card">
    <h3>⭐ 战技点</h3>
    ${kv('变化',`${r.old_sp} → ${r.new_sp} (${r.delta>=0?'+':''}${r.delta})`)}
    ${kv('上限',r.sp_cap)}${kv('原因',r.reason)}${kv('来源',r.source_id)}
  </div>`;
}

function energyCard(r){
  return `<div class="rec-card">
    <h3>⚡ 能量</h3>
    ${kv('目标',r.unit_id)}${kv('来源',r.source_type)}${kv('标签',r.label)}
    ${kv('变化',`${r.old_energy} → ${r.new_energy} (${r.delta>=0?'+':''}${r.delta})`)}
    ${kv('上限',r.max_energy)}
  </div>`;
}

function shieldCard(r){
  return `<div class="rec-card">
    <h3>🛡️ 护盾</h3>
    ${kv('目标',r.unit_id)}${kv('变化',`${r.old_shield} → ${r.new_shield} (${r.delta>=0?'+':''}${r.delta})`)}
    ${kv('原因',r.reason)}${kv('来源',r.source_id)}
  </div>`;
}

function hpCard(r){
  return `<div class="rec-card">
    <h3>❤️ 血量</h3>
    ${kv('目标',r.unit_id)}${kv('变化',`${r.old_hp} → ${r.new_hp} (${r.delta>=0?'+':''}${r.delta})`)}
    ${kv('原因',r.reason)}${kv('过量',r.overkill)}${kv('来源',r.source_id)}
  </div>`;
}

function avCard(r){
  return `<div class="rec-card">
    <h3>⏱️ 行动值</h3>
    ${kv('目标',r.unit_id)}${kv('变化',`${r.old_remaining_av} → ${r.new_remaining_av}`)}
    ${kv('原因',r.reason)}
  </div>`;
}

function turnCard(r){
  return `<div class="rec-card">
    <h3>🔄 回合</h3>
    ${kv('单位',r.unit_id)}${kv('类型',r.turn_kind)}${kv('事件',r.event)}
  </div>`;
}

function mechanicCard(r){
  return `<div class="rec-card">
    <h3>⚙️ 机制</h3>
    ${kv('来源',r.source_unit_id)}${kv('键',r.mechanic_key)}${kv('值',r.mechanic_value)}
    ${kv('操作',r.operation)}${kv('原因',r.reason)}
  </div>`;
}

function renderRecords(settlement){
  let html='';
  let types={
    damage:{list:settlement.damage_records||[],fn:damageCard,icon:'💥',label:'伤害'},
    status:{list:settlement.status_records||[],fn:statusCard,icon:'📌',label:'状态'},
    sp:{list:settlement.sp_records||[],fn:spCard,icon:'⭐',label:'战技点'},
    energy:{list:settlement.energy_records||[],fn:energyCard,icon:'⚡',label:'能量'},
    shield:{list:settlement.shield_records||[],fn:shieldCard,icon:'🛡️',label:'护盾'},
    hp:{list:settlement.hp_records||[],fn:hpCard,icon:'❤️',label:'血量'},
    av:{list:settlement.av_records||[],fn:avCard,icon:'⏱️',label:'行动值'},
    turn:{list:settlement.turn_records||[],fn:turnCard,icon:'🔄',label:'回合'},
    mechanic:{list:settlement.mechanic_records||[],fn:mechanicCard,icon:'⚙️',label:'机制'},
  };
  for(let [key,t] of Object.entries(types)){
    if(currentTab!=='all' && currentTab!==key)continue;
    if(!t.list.length)continue;
    html+=`<h2>${t.icon} ${t.label} (${t.list.length})</h2>`;
    t.list.forEach(r=>{html+=t.fn(r)});
  }
  if(!html)html='<div class="empty-hint">此步骤无结算记录（可能是准备阶段或队列排空）</div>';
  return html;
}

function renderSceneSnapshot(scene){
  let html='';
  let g=scene.global||{};
  html+=`<div class="rec-card">
    <h3>🌐 全局状态</h3>
    ${kv('AV',g.av)}${kv('Cycle',g.cycle)}
    ${kv('skill_points',g.skill_points)}${kv('_sp (整数)',g._sp)}
    ${kv('skill_point_cap',g.skill_point_cap)}${kv('_sp_cap (整数)',g._sp_cap)}
    ${kv('wave_index',g.wave_index)}
  </div>`;

  ['allies','enemies','summons'].forEach(side=>{
    let units=scene[side]||[];
    units.forEach(u=>{
      let statusesHtml='';
      (u.statuses||[]).forEach(st=>{
        let cn=st.status_name_cn||'';
        let tp=st.status_type||'';
        let badge='';
        if(tp==='Buff')badge='<span class="badge badge-buff">Buff</span>';
        else if(tp==='Debuff')badge='<span class="badge badge-debuff">Debuff</span>';
        let label=cn||st.id||'?';
        statusesHtml+=`<span class="scene-status">${esc(label)}${badge}</span>`;
      });
      html+=`<div class="scene-unit">
        <h4>${esc(u.name||u.id)} (${side}) ${u.alive?'✅':'❌'}</h4>
        ${kv('HP',`${u.resources?.hp||'?'} / ${u.resources?.max_hp||'?'}`)}
        ${kv('护盾',u.resources?.shield)}${kv('能量',`${u.resources?.energy||'?'} / ${u.resources?.max_energy||'?'}`)}
        ${kv('韧性',u.resources?.toughness!==null?u.resources?.toughness+' / '+u.resources?.max_toughness:'N/A')}
        ${kv('剩余AV',u.action_axis?.remaining_av)}
        <div style="margin-top:6px">${statusesHtml||'<span class="nocn">无状态</span>'}</div>
      </div>`;
    });
  });
  return html;
}

function renderMain(){
  if(currentStep<0||currentStep>=allSteps.length){$('main').innerHTML='<div class="empty-hint">请从左侧选择一个步骤</div>';return;}
  let step=allSteps[currentStep];
  let settlement=step.settlement||{};
  let scene=step.scene||{};

  let tabHtml='';
  ['all','damage','status','sp','energy','shield','hp','av','turn','mechanic'].forEach(t=>{
    tabHtml+=`<button class="tab-btn${t===currentTab?' active':''}" data-tab="${t}" onclick="selectTab('${t}')">${t==='all'?'全部':t}</button>`;
  });

  let html=`<h2 style="margin-bottom:12px">${esc(step.step_label||('Step '+currentStep))}</h2>
    <div class="tab-bar">${tabHtml}</div>
    <details><summary>📋 结算记录</summary>${renderRecords(settlement)}</details>
    <details open><summary>📷 场景快照</summary>${renderSceneSnapshot(scene)}</details>`;

  $('main').innerHTML=html;
}

// Init
document.addEventListener('DOMContentLoaded',()=>{
  // allSteps injected by Python
  renderSidebar();
  if(allSteps.length>0){selectStep(0);}
});
"""


# ── 数据提取 ────────────────────────────────────────────────────────────────

def extract_step_label(step: dict, index: int) -> str:
    """从 route step 提取人类可读标签。"""
    actor = step.get("actor_id", step.get("actor", "?"))
    action = step.get("action_id", step.get("action", "?"))
    mode = step.get("timing_mode", step.get("mode", ""))
    cn = step.get("meta", {}).get("cn", "")
    parts = [f"#{index}"]
    if cn:
        parts.append(cn)
    parts.append(f"{actor}/{action}")
    if mode:
        parts.append(f"[{mode}]")
    return " ".join(parts)


def collect_trace(result: dict, route: list[dict]) -> list[dict]:
    """从 run_route 结果和原始 route 中提取合并的步骤数据。"""
    trace = result.get("metadata", {}).get("route_action_trace", [])
    if not trace:
        # fallback: try scene.trace
        trace = result.get("scene", {}).get("trace", [])
    steps = []
    for i, t in enumerate(trace):
        step_info: dict = {}
        if i < len(route):
            step_info["step_label"] = extract_step_label(route[i], i)
        else:
            step_info["step_label"] = f"Step {i}"
        step_info["settlement"] = t.get("settlement", {})
        # scene comes from after_scene in trace entries, or global scene
        step_info["scene"] = t.get("after_scene", result.get("scene", {}))
        steps.append(step_info)
    # If still empty, include one entry with full scene (for cases with no route)
    if not steps and result.get("scene"):
        steps.append({
            "step_label": "初始场景 (无route步骤)",
            "settlement": {},
            "scene": result["scene"],
        })
    return steps


# ── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 2.5 结算验证 UI")
    parser.add_argument("case", help="案例 YAML 路径")
    parser.add_argument("--tbgd", default=None, help="TBGD 数据目录路径")
    parser.add_argument("--steps", type=int, default=30, help="最多执行步数")
    parser.add_argument("--output", default=None, help="HTML 输出路径（默认自动命名）")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    case_path = Path(args.case)
    if not case_path.exists():
        print(f"[ERROR] 案例文件不存在: {case_path}")
        sys.exit(1)

    has_tbgd = False
    tbgd = None
    if args.tbgd:
        tbgd_path = Path(args.tbgd)
        if tbgd_path.exists():
            tbgd = TBGDSource.open(str(tbgd_path))
            has_tbgd = True
        else:
            print(f"[WARN] TBGD 目录不存在: {tbgd_path}，将不使用注册表")

    print(f"[1/3] 加载案例: {case_path.name}")
    case = load_case(str(case_path))
    route = case.get("route", [])[:args.steps]
    print(f"     route steps: {len(route)}")

    print(f"[2/3] 运行引擎 (TBGD={'yes' if has_tbgd else 'no'})...")
    sim = BattleSimulator(case, tbgd_source=tbgd)
    result = sim.run_route(route)
    trace_entries = result.get("metadata", {}).get("route_action_trace", [])
    if not trace_entries:
        trace_entries = result.get("scene", {}).get("trace", [])
    print(f"     trace entries: {len(trace_entries)}")

    print("[3/3] 生成 HTML...")
    steps = collect_trace(result, route)

    # 检查中文名覆盖
    cn_count = 0
    total_status = 0
    for s in steps:
        for sr in s.get("settlement", {}).get("status_records", []):
            total_status += 1
            if sr.get("status_name_cn"):
                cn_count += 1

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Phase 2.5 结算验证 — {case_path.name}</title>
{HTML_CSS}
</head>
<body>
<div id="app" style="display:flex;flex-direction:column;width:100vw;height:100vh">
<div class="header-bar">
  <span class="title">▸ Phase 2.5 结算验证</span>
  <span class="meta">案例: {case_path.name}</span>
  <span class="meta">TBGD: {'✅ 已加载' if has_tbgd else '❌ 未使用'}</span>
  <span class="meta">步骤: {len(steps)}</span>
  <span class="meta">状态中文名: {cn_count}/{total_status}</span>
  <span class="meta" style="margin-left:auto">子临的工具</span>
</div>
<div style="display:flex;flex:1;overflow:hidden">
  <div id="sidebar"></div>
  <div id="main"><div class="empty-hint">加载中…</div></div>
</div>
</div>
<script>
const ALL_STEPS = {json.dumps(steps, ensure_ascii=False, default=str)};
let allSteps=ALL_STEPS;
{HTML_JS}
// Re-trigger init
document.addEventListener('DOMContentLoaded',()=>{{
  renderSidebar();
  if(allSteps.length>0){{selectStep(0);}}
}});
// Fire immediately if DOM already loaded
if(document.readyState!=='loading'){{
  renderSidebar();
  if(allSteps.length>0){{selectStep(0);}}
}}
</script>
</body>
</html>"""

    output_path = Path(args.output) if args.output else (case_path.parent / f"{case_path.stem}_validate.html")
    output_path.write_text(html, encoding="utf-8")
    print(f"     OK -> {output_path}")

    if not args.no_open:
        webbrowser.open(str(output_path.resolve()))
        print("     浏览器已打开")

    print(f"\n完成。状态中文名覆盖: {cn_count}/{total_status}")
    if has_tbgd and total_status > 0 and cn_count == 0:
        print("  [WARN] 有 TBGD 但无中文名 -> 当前案例使用的状态 ID 不是整数 StatusID（可能是模型定义的字符串 ID）")


if __name__ == "__main__":
    main()

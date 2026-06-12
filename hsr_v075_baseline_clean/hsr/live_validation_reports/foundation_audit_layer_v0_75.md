# v0.75 基础改造：场面快照与行动结算审计层

## 目的

本轮不改变 v0.74 的战斗数值逻辑，先给模拟器加一层可审计输出，让每一步行动后都能看到：

1. 当前完整场面；
2. 本次行动过程的结算账本；
3. 每段直接伤害的公式乘区来源。

这样可以避免继续靠手记倒推 Buff/Debuff 和伤害区来源。

## 已修改文件

- `simulator_v7_7/hsr_simulator_prototype_v7_7.py`

## 新增输出结构

### 1. 顶层最终场面

`result()` 现在除 `state` 外，新增：

```json
"scene": { ... full_scene_snapshot ... }
```

### 2. 每步 route trace 的完整场面

`metadata.route_action_trace[*]` 现在新增：

```json
"before_scene": { ... },
"action_resolution": { ... },
"after_scene": { ... }
```

保留旧字段：

```json
"before": { ... compact snapshot ... },
"after": { ... compact snapshot ... },
"event_summary": { ... }
```

因此旧的 route assertion / smoke harness 不会因为字段缺失被破坏。

## full_scene_snapshot 覆盖内容

### global

- 当前 AV
- cycle
- 战技点 / 战技点上限
- wave_index
- global flags

### action_axis

每个在行动轴上的单位：

- id / name / side / alive
- 当前速度
- 行动间隔 `10000 / speed`
- remaining_av 原数
- absolute_av = 当前全局 AV + remaining_av
- tags

### allies / summons / enemies / others

每个实体记录：

- 生命、最大生命、生命百分比
- 护盾
- 能量 / 能量上限
- 韧性 / 最大韧性 / 是否破韧
- 血条模型、血条数量、是否跨条继承伤害
- 行动轴位置
- 当前面板属性
- stat_base / stat_pct / stat_flat / legacy_stats
- 抗性
- 弱点
- Buff/Debuff：id、source_id、层数、最大层数、持续类型、剩余持续、是否额外回合消耗、tags、modifier_keys、完整 modifiers
- 特殊机制：phase、战甲/荣耀/计数器/召唤绑定/敌人 AI 序列等能从 flags/status payload 提取的内容
- flags 原始记录

### queues

- ultimate_queue
- immediate_queue
- interrupt_queue

## action_resolution 覆盖内容

每步行动会输出：

- requested：路线指定的 actor/action/timing/targets
- damage_events：伤害事件与跳过伤害事件
- status_events：挂状态、移除状态、持续时间跳动、相关 effect
- resource_events：能量、SP、护盾、生命等资源变化
- av_events：拉条、行动轴、回合开始/结束、队列事件
- mechanism_events：怪物机制、触发器、破韧、韧性、转阶段、击杀、波次等事件
- all_events：本步所有原始日志事件，按发生顺序保留

## damage formula ledger

每个普通直接伤害事件的 `data` 中新增：

```json
"formula_ledger": {
  "formula": "base * crit * dmg_bonus * defense * res * damage_taken * universal_reduction * toughness_state * other",
  "scaling": { ... },
  "crit": { ... },
  "buckets": {
    "dmg_bonus": { "multiplier": ..., "terms": [...] },
    "defense": { "multiplier": ..., "terms": [...] },
    "res": { "multiplier": ..., "terms": [...] },
    "damage_taken": { "multiplier": ..., "terms": [...] },
    "universal_reduction": { "multiplier": ..., "terms": [...] },
    "toughness_state": { ... },
    "other": { ... }
  },
  "final_damage": ...
}
```

每个 term 会尽量记录：

- source_type：actor.stats / actor.status / target.status / packet 等
- source_id：状态 id 或 packet id
- key：进入哪个 modifier key
- value：原始值
- stacks：层数
- applied_value：实际计入值
- note：来源、是否非逐层等补充说明

## 当前复跑结果

复跑 case：

```bash
cd /mnt/data/hsr_fixed_workspace/current/simulator_v7_7
python3 hsr_simulator_prototype_v7_7.py \
  --model-pack ../model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output ../validation_outputs_v0_75/c0_to_c8_full_audit_v0_75.json
```

结果：

- route_assertions.ok = true
- route step count = 8
- log events = 172
- 输出文件大小约 1.47 MB

关键伤害数值未改变：

- 缇宝追击：2312.108210 + 2080.897389 = 4393.005600
- 希儿战技四段：27496.850523 / 2966.116652 / 2966.116652 / 82490.551568

## 仍未解决的问题

这轮只是把“记录能力”补上，还没有把模拟器彻底改成 raw team/stage -> battle assembly 的完整流程。当前仍然是 compiled case/checkpoint replay。

下一步应继续做：

1. 把状态变更事件从宽泛的 `effect` 拆成 `status_add/status_remove/resource_change/sp_change/av_change` 等强类型事件；
2. 给每个 action 建立 ActionSettlement 对象，而不是只从 log 反查；
3. 给每个 Buff/Debuff 增加稳定中文名/机制名字段，避免只有内部 id；
4. 给敌人行动意图建立明确字段，不能只靠 `default_probe_action_id` 推断；
5. 给暴击、命中、抵抗、目标选择建立 RNG/event ledger；
6. 建立 raw team/stage assembly：队伍、光锥、遗器、敌人、关卡、秘技 -> 初始 BattleState。

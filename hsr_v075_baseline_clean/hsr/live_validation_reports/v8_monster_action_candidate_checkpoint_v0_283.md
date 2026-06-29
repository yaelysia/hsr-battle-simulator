# v8 怪物固定序列行动候选检查点 v0_283

## 本阶段完成

- 新增 `EnemyActionSystem` 与 `EnemyActionCandidate`。
  - 只读 `BattleState + RuleBook`，从单位 flags 的 `monster_data_card_id` 定位 `MonsterDataCardIR`。
  - 从 `MonsterDataCardIR.action_sequence` 和 `enemy_action_sequence_cursor` 读取下一条固定序列动作。
  - 输出候选动作、动作等级、目标模式、可选目标、自动目标组、阻塞原因和来源追踪。
  - 候选生成不产生 mutation。

- 扩展 `TargetSystem.enumerate_action_targets`。
  - `single/blast/bounce` 枚举敌对存活单位作为可选主目标。
  - `aoe` 枚举自动目标组。
  - `self_or_team` 枚举自身与同阵营合法目标。
  - 该接口只用于展示和推演分支，最终执行仍走 `resolve_action_targets`。

- 接入 scheduler。
  - 队列仍优先于自然行动。
  - 自然轮到敌方且无队列 drain 时，scheduler 写入 process-only 的 `enemy_action_candidate` 记录和事件。
  - scheduler 不自动执行候选，不自动选择目标。
  - 外部传入匹配候选的标准 `ActionCommand` 且执行成功后，才推进 `enemy_action_sequence_cursor`。
  - 动作不匹配、目标缺失、目标非法、候选 blocked、执行 blocked 时不推进 cursor。

- 接入 UI 测试台。
  - 有敌方固定序列候选时不再默认临时跳过敌方回合。
  - `action_prompt` 展示敌方候选、目标模式、可选目标和阻塞原因。
  - 前端目标点击不再写死“只能点敌方”，而是按报告里的候选目标列表判断。
  - `auto_skip_enemy_turns` 保留为调试选项，但不会跳过已有候选的敌方回合。

- 扩展 source audit。
  - 新增 `enemy_action_system` mutation source 策略。
  - 仅允许该系统修改 `units/<enemy>/flags/enemy_action_sequence_cursor`。
  - 审计反查 `MonsterDataCardIR.action_sequence`、AI 固定序列 admission、序列 step 和 `ActionDefinitionIR`。

## 验证样例

- `validate_v0_283` 使用结构化谓词选择样例，不按固定 MonsterID 作为主路径。
- 当前实际选中样例：
  - 中文名：直播小助手
  - 英文名：Live Stream Assistant
  - `MonsterID=5014011`
  - `entity_ref=monster:5014011`
  - 固定序列长度：2
- 这里的 Assistant 是怪物显示名，不代表 assistant/召唤物系统已接入。

## 已验证

- 敌方自然回合能产出候选，且候选本身不产生战斗 mutation。
- 外部按候选生成命令后，动作执行成功并推进 cursor。
- 下一次候选读取推进后的 cursor，切到下一条序列。
- 缺怪物卡、缺序列、缺动作、复杂 AI、目标为空、目标非法均 blocked，且不推进 cursor。
- 队列分支优先于自然敌方候选。
- UI runner 在候选存在时不自动跳过敌方回合。

## 未完成

- 没有做复杂 AIPath、随机策略、阶段切换、召唤、波次、关卡倍率。
- 没有让 runtime 自动替敌人选目标。
- 没有把敌方动作接入完整推演策略；当前目标由 UI、用户或未来推演器提供。
- 没有覆盖所有怪物动作目标类型和所有怪物机制。

## 距离最小敌方行动纵切还缺

- UI 中更完整地展示敌方候选的动作来源和序列 cursor。
- 推演器侧目标分支枚举和结果分叉。
- 更多普通怪物固定序列样例的覆盖，包括 single、blast、aoe、bounce。
- 敌方动作中的状态附加、回调、队列插入等机制继续按来源 admission 扩展。

## 距离完整复刻还缺

- 完整敌方机制入口：阶段机制、事件监听、召唤、锁血、特殊行动窗口。
- 波次与关卡配置，包括关卡等级、HardLevelGroup、环境机制。
- 光锥、内外圈遗器和套装效果。
- 全角色卡、全怪物卡、全机制样例的人工解释与验证。
- 战斗推演策略层：敌我动作目标分支、终结技插队选择、随机事件分支和搜索剪枝。

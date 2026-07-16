# P8-S6 光锥动态能力图与启动注册 ready_for_review

日期：2026-07-16
基线检查点：`b7ed417`（P8-S5）
状态：`ready_for_review`

本轮未修改 P8 Checklist，未创建 Git commit，未进入 P8-S7。

## 实现结果

- S3 的 162 条已发布光锥能力记录均以“完整来源路径 + 原始 `AbilityList` 行号”生成唯一 `StandaloneAbilityGraphIR`；图身份不使用能力名称，也不复制第二套装备效果 payload。
- 162 条光锥机制引用、407 条 `SkillEquip` 参数读取进入 Canonical IR/RuleBook。独立 raw oracle 同样发现 407 条读取，逐条完整 JSON 路径、参数类型、动态变量身份、参数序号、规范读取身份和值来源指纹完全一致；只属于能力记录路径前缀但不对应真实节点的读取会被拒绝。
- 5 个叠影档位共完成 2,035 次精确参数绑定。ValueResolver 直接核对正式光锥定义、技能、叠影档、参数值及来源，全程保留规范十进制字符串，不经过 `float`。
- 装配结果只保存图、实例、佩戴者、叠影和参数绑定的稳定引用。RuleBook 会拒绝重复图、重复参数读取、错图来源、错读取来源和跨光锥机制错绑。
- 通用 provider 的语义唯一键固定为“单位 + 装备实例 + 机制”，不再受可变选择 ID 影响；请求内重复项和状态内重复项均 fail-closed。注册发生在 `UnitState` 创建之后，批量预检后经同一 reducer 原子提交；多佩戴者 provider 身份隔离。
- 聚焦正式场景通过 `ScenarioStateBuilder` 完整构筑链建立单位后产生唯一 provider setup mutation；`UnitState` 快照编解码恢复后再次注册保持幂等，重新构建场景也只产生一份 provider，未通过直接调用注册函数替代正式消费链。
- scenario 仅消费装配后的动态选择和 Canonical IR；provider 层不读取 TBGD、构筑输入或 S3 raw schema，也没有新增装备专用事件循环。

## 当前数据事实与诚实阻断

- 当前 162 个生产装备能力图都含尚未完整 lowering 的嵌套 modifier 图，因此：
  - `production_executable_graph_count = 0`
  - `production_partial_graph_count = 162`
- 所有同命途真实光锥仍生成只读静态面板，但动态选择为 `blocked`，正式战斗保持 blocked/state unchanged；没有执行已 lower 的局部 task。
- 命途失配仍为装配成功、基础属性生效、零动态 provider、战斗准入。
- S6 验证中的 executable 图仅用于验证通用 provider 生命周期、幂等性和 owner 隔离，不作为任何装备 gameplay family 已完成的证据。嵌套 modifier/callback family 继续归类为 `implementation_missing`，由 P8-S7/P8-S8 承接。

## 负例与来源反查

固定 20 项负例全部通过，覆盖：缺失/重复图、错图来源、重复参数读取、错参数读取来源、不存在的动态 hash 路径、伪造参数类型、跨光锥机制错绑、越界参数、owner 错绑、读取集合缺失、精确值伪造、结果模型的伪节点来源、同一 provider 的选择 ID 别名、请求内语义重复、ValueResolver 值/来源伪造、旧 JSON 字段和 float 数值。

一条启动审计链已固定为：

```text
provider registration record
-> graph_ref_id + parameter_binding_ids
-> EquipmentMechanismRefIR / EquipmentAbilityParameterReadIR
-> S3 LightConeAbilitySourceIR
-> Config/ConfigAbility/Equip/.../AbilityList[row]
```

审计说明文字不参与运行时选择；稳定来源身份参与 RuleBook、ValueResolver 和 provider 的 fail-closed 核对。

## 串行验证

以下命令均以 `ionice -c 3 nice -n 15` 串行执行，输出仅写入 `/tmp`：

```text
validate_p8_s6_light_cone_dynamic_startup: ok=true
  162 definitions / 162 graphs / 407 raw+IR reads / 2,035 exact comparisons / 20 negatives
  formal ScenarioStateBuilder startup / setup mutation / snapshot restore / rebuild: passed
validate_p8_s1_equipment_type_contract: ok=true
validate_p8_s4_light_cone_instance_assembly: ok=true
validate_p5_s1_value_binding_contract: ok=true, 21 rows
validate_p7_s3_selected_graph_atomic_commit: ok=true, 9 cases
compileall: passed
git diff --check: passed
```

S6 主产物总计约 1.9 MiB；没有序列化完整 CanonicalIR、完整 RuleBook 或 transition dump。P5 完整 lowering 回归单独串行执行，未与其他验证并发。

未运行 P7-S9：本轮没有修改 P7 event/executor，执行卡允许由 S6 内的原子失败、重复注册、snapshot 和多 owner 矩阵替代其中一项重回归。未运行 P1-P7 阶段聚合、全光锥 transition 或 `validate_v0_209`，因为与本阶段改动无直接契约关系且会增加无意义资源峰值。

## 剩余距离

- 最小同命途光锥战斗纵切仍缺 P8-S7/S8 对当前嵌套 modifier/callback gameplay family 的完整 lowering、准入、执行、settlement 与 replay。
- 完整 P8 仍缺后续光锥动态扩面、遗器定义/实例/套装装配、最终构筑纵切及聚合验收。

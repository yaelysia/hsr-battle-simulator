# P9-S3 Obfuscated Source Resolution - ready_for_review

## 范围与基线

- 基线：`637398b6b608612764eb51cbb3df4ac31778296a`
- 唯一范围：`P9-S3_OBFUSCATED_SOURCE_RESOLUTION`
- 未修改 Checklist、总计划、`CODEX_HANDOFF.md`、runtime handler 或用户已有修改。
- 未运行完整 lowering、P1-P8 聚合或相邻阶段验证。

## 生产事实

- 当前 S0 来源指纹：`349d9dd2ade62d32e17b25a49400c8043dfdf0cea73250aa0ee4bc23fcedb998`。
- `decode_required` 集合由当前目录动态得到：7 个家族、213 条记录；该数量只作为本次 evidence，不是固定门槛。
- 当前 `Config/ConfigAbility` 闭包：2844 个 JSON、138579692 bytes；全部读取和解析成功，未发现数据包截断。
- package manifest 指纹：`cf203fab1a3857ae2ebca0811d81dd97dd831cbfd82f7bf5e4c4c036111b6be1`。

| 家族 | 当前记录 | 裁决 | 类型化责任包 |
|---|---:|---|---|
| `LAJIKDENEOO` | 88 | `decoded_to_package` | dynamic-value write；保留 target/key/value/显式或缺省 operation 原貌 |
| `NKLOMENKLHK` | 13 | `decoded_to_package` | dynamic-value definition |
| `IKDAKCBKFAB` | 3 | `decoded_to_package` | action-queue precheck 的 metric/threshold；未补 comparator 或 runtime 语义 |
| `TargetAlias` | 103 | `decoded_to_package` | target-expression alias；它因父分支终止作用域继承进入当前 decode 集合 |
| `FFMONJGCKDI` | 3 | `source_gap_blocked` | 混淆语义缺少同包充分证据 |
| `LAPKGFCDPCD` | 1 | `source_gap_blocked` | 混淆语义缺少同包充分证据 |
| `LPMGDCDFOOE` | 2 | `source_gap_blocked` | 混淆语义缺少同包充分证据 |

成功 lower 207 条；其余 6 条保持 blocked。所有 decoded IR 均为不可变、可序列化对象，带真实 S0 `IRSource`、明确 `package_owner`，并固定 `runtime_admission=not_admitted`。

## 主线程五项阻断与根因修复

主线程实证的五项构造边界绕过均已复现为构造器缺少闭包，而非验证器问题：

1. definition candidate 的 `json_path` 未进入 candidate 稳定身份。
2. decoded source 的 `source_path` 未进入 decoded/scope 身份闭包。
3. resolved reference 的 `package_owner` 只是任意非空字符串，且 catalog 未与 candidate owner 对账。
4. 数值表达式只检查 `schema_version/kind` 存在，允许额外字段和畸形 instruction。
5. family 的等价证据是无类型 `tuple[str]`，无法校验路径、digest 或字段角色。

本轮修复：

- 将 decoded 责任包和 ability-definition 来源包拆成两套互不混用的 `Literal` 枚举；decoded kind 与 owner 一一绑定，candidate owner 还须匹配 `ConfigAbility` 路径分域，reference owner 必须等于唯一 candidate owner。
- decoded source 从 occurrence kind、source path、json path、family 重算 S0 scope ID，并从这些字段重算 decoded ID；definition candidate 与 ability-task reference 从自身来源字段重算 ID；source-graph gap 从现有 relation 字段、gap kind 和 S1 candidate 集重算 relation/gap ID。
- 在统一 `rules/expression_ir.py` 增加 canonical numeric-expression exact validator；严格拒绝未知顶层字段、未知 instruction 字段、非法 opcode、栈下溢、非法 end 和非单值终态。
- 等价证据改为不可变 `CharacterEquivalentStructureEvidenceIR`，包含真实 source path、json path、raw type、digest、observed fields 和字段角色映射，且自身稳定 ID 覆盖全部字段。
- 全包扫描实际读取未混淆 `DefineDynamicValue` / `SetDynamicValue` 节点，并验证 target/key/value 角色的值可规范化；若没有完整兼容候选，整族 blocked。当前完整包存在兼容候选，因此两个动态值族仍可诚实 decoded。
- `IKDAKCBKFAB` 仅在全部 3 条记录均位于 `TurnInsertAction.PreCheck`、metric 原值均为 `SameTagInsertUnusedCount`、threshold 均为 exact canonical numeric expression 时 lower 中性 metric/threshold；未引入 comparator。`TargetAlias` 只接受真实 `RPG.GameCore.TargetAlias` 直接证据。

## 能力引用闭包

- 结构化裁决覆盖 41 个 S1 gap 和 37 个任务级未解析引用，共 78 个 subject。
- 当前请求名称 45 个，定位到 41 个定义候选。
- 完整包检索后仍无候选的 4 个名称：
  - `Avatar_Advanced_Sparkle_00_Skill02_Others_Camera`
  - `Avatar_Advanced_Sparkle_00_Skill02_Self_Camera`
  - `Avatar_Herta_00_PassiveAtkReady_Ability_Trigger`
  - `Avatar_TingYun_00_SkillMazeInLevel`
- 另保留 6 个 S1 关系缺口：3 个 `cross_character_blocked`、3 个 `missing_entry_blocked`。它们未被误报成全包缺失。
- 没有分支达到“完整证明 non-gameplay”的强度，因此本阶段没有强行产生 `non_gameplay` 裁决。

## 验证

Fast：

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
  simulator_v8_clean_core/rules/expression_ir.py \
  simulator_v8_clean_core/rules/ir.py \
  simulator_v8_clean_core/rules/__init__.py \
  simulator_v8_clean_core/tbgd/character_source_resolution.py \
  simulator_v8_clean_core/tbgd/lowering.py \
  simulator_v8_clean_core/tbgd/__init__.py \
  simulator_v8_clean_core/tools/validate_p9_s3_obfuscated_source_resolution.py
git diff --check -- simulator_v8_clean_core/rules/__init__.py \
  simulator_v8_clean_core/rules/expression_ir.py \
  simulator_v8_clean_core/rules/ir.py \
  simulator_v8_clean_core/tbgd/__init__.py \
  simulator_v8_clean_core/tbgd/lowering.py
```

结果：通过。新增未跟踪 Python 文件另以尾随空白定向检查通过。

必要 direct 主验证：

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m \
  simulator_v8_clean_core.tools.validate_p9_s3_obfuscated_source_resolution \
  --tbgd-root ../../turnbasedgamedata-main \
  --output-dir /tmp/p9_s3_boundary_fix_final_637398b
```

结果：exit 0，`ok=true`、`ready_for_review=true`。以下执行卡谓词全部符合：

- `decode_required_set_current=true`
- `all_decode_items_have_structured_resolution=true`
- `decoded_items_have_typed_ir_and_package_owner=true`
- `undecoded_items_remain_blocked=true`
- `missing_ability_search_closure_complete=true`
- `source_gap_not_caused_by_scan_or_lowering=true`
- `text_or_observation_used_as_rule_source=false`
- `obfuscated_specific_runtime_handlers=0`

construction/negative matrix 共 23 个攻击与负例，全部通过，包括五个原始攻击、任意/合法但错误 owner、伪 equivalent path/json path/digest/字段角色、动态值候选不兼容整族 blocked、queue context/metric 改写 blocked，以及 extra expression/instruction 字段拒绝。

最终资源：11.752362 秒，342892544 bytes peak RSS，224295 bytes evidence，验证器 680 非空行。预算分别为 480 秒、1 GiB、5 MiB、900 行，全部通过。

本轮一次失败重跑：在额外收紧 decoded 上游 scope identity 后，首次误用了全长通用稳定 ID，而现有 S0 scope 契约是 NUL 分隔输入的 24 位截断哈希，导致 decoded 全部 fail-closed，construction 尚未执行。改为精确复用 S0 身份算法后，fresh 主验证通过。此前旧报告记录的两项验证器 false negative 保留为历史，不影响本轮最终 evidence。

Evidence：

- `/tmp/p9_s3_boundary_fix_final_637398b/summary.json`
- `/tmp/p9_s3_boundary_fix_final_637398b/family_resolution.json`
- `/tmp/p9_s3_boundary_fix_final_637398b/ability_reference_resolution.json`
- `/tmp/p9_s3_boundary_fix_final_637398b/source_search_summary.json`
- `/tmp/p9_s3_boundary_fix_final_637398b/negative_matrix.json`

## 修改文件

- `simulator_v8_clean_core/rules/ir.py`
- `simulator_v8_clean_core/rules/expression_ir.py`
- `simulator_v8_clean_core/rules/__init__.py`
- `simulator_v8_clean_core/tbgd/character_source_resolution.py`
- `simulator_v8_clean_core/tbgd/lowering.py`
- `simulator_v8_clean_core/tbgd/__init__.py`
- `simulator_v8_clean_core/tools/validate_p9_s3_obfuscated_source_resolution.py`
- `live_validation_reports/P9-S3_OBFUSCATED_SOURCE_RESOLUTION_ready_for_review.md`

## Deferred / Gap

- 3 个混淆家族、6 条当前记录继续 `source_gap_blocked`；没有根据字段名、角色或观测结果猜测语义。
- 4 个精确能力名称在当前完整包中无定义候选，继续 `source_gap_blocked`。
- 6 个既有 S1 关系归属缺口继续 blocked。
- S3 只建立类型化 IR、lowering 与责任包归属；runtime 消费、S4 以及上述来源缺口的未来裁决均未进入本次范围。

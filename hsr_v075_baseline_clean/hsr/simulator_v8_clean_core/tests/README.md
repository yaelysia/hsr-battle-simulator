# 验证入口

从仓库根目录使用已有 uv `.venv`，不创建环境、不安装依赖。
先选受影响的行为，再选最小检查范围；不按历史阶段把所有命令逐项运行。
当前支持与待修问题见[交接](../../CODEX_HANDOFF.md)，验证成本约定见
[工作方式](../docs/AGENT_WORKFLOW_AND_VALIDATION.md#验证选择)。

## 快速检查

默认排除 `integration`。示例：

```bash
.venv/bin/python -B -m pytest \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_compile_cache.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_content_processor_combat.py
```

按问题换文件或加 `-k`。`--collect-only -q` 只核对用例是否能收集，不证明行为通过。
省略文件路径才会运行全部普通回归；仅在广泛变更或版本验收需要时使用。

| 改动范围 | 直接入口 |
| --- | --- |
| 处理器接管、增伤、失败回滚 | `test_content_processor_combat.py`、`test_content_processor_interface.py` |
| 多层韧性和溢出 | `test_multilayer_toughness.py` |
| 伤害与临时贡献 | `test_damage_formula_reconciled_rules.py`、`test_damage_modifier_transport.py` |
| 编译缓存与 IR 身份 | `test_compile_cache.py`、`test_ir_import_identity.py` |
| 装备范围裁剪、参数与依赖闭包 | `test_equipment_scope.py`（integration；与全目录定义对照，含空光锥/仅外圈/仅内圈与共享池） |
| 诊断精简与数值保留 | `test_diagnostic_output.py`；跨模式公开路线见下方公共接口基线 |
| 归档与会话分支 | `test_battle_archive.py`、`test_session_fork.py` |
| 装备输入与消费 | `test_equipment_input_codec.py`、`test_equipment_heal_formula_delay_cost.py`；完整装备路线另按需选择 |
| 装备来源查询与可选审计 | `test_equipment_source_query.py`（integration，真实构筑注册结算） |
| 工作台请求 | `test_live_battle_ui.py`；监听端口/浏览器检查与内存请求检查分开报告 |

快速机制检查用于定位公式、时序、原子性等具体错误，保留这些检查的行为价值。
重构时优先迁移绑定私有返回形状、旧审计结构的断言，不批量删除所有内部检查。
`test_p9_a2_direct_static_context.py` 会构建真实规则目录，已归入 integration，默认快测不再隐式执行它。

## 真实入场与公开操作

需要真实编译或正式场景时显式选择 `integration`：

```bash
.venv/bin/python -B -m pytest -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_content_processor_combat.py
```

此文件验证正式入场后的处理器 H1/H2 接线，处理器本身是明确标注的组件输入，不能当作完整角色验收。
遐蝶当前完整路线入口为 `test_v1_summon_routes.py::test_castorice_joint_breath_finisher_resummon_lifetime_and_equipment`，
覆盖吐息、终结、重召、寿命到期与锁血；`test_content_processor_castorice.py` 保留早期处理器检查。

公开操作路线应检查当前合法选择、命令成功、必要数值和后续可继续操作。
参考输出用于工程回归，不代替游戏实测或成熟计算器；不要自动把当前输出批准为正确答案。
首次得到有效路线后保留归档，后续未影响该结果的检查直接读取证据。

公共接口基线入口：

```bash
.venv/bin/python -B -m pytest -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_public_battle_routes.py
```

它通过公开查询/提交核对固定路线的逐步数值与 RNG，比较精简/完整诊断、历史分支和归档恢复；
同时验证两支队伍共用编译池时选择与结算不变。参考值在 `tests/golden/`，是现有行为基线，
没有游戏数值正确性的背书。之后重构优先依赖此类业务检查，内部测试按其实际价值逐步迁移。

## 独立回放与资源

运行和回放示例见[CLI 操作](../CLI_MVP.md#固定操作与回放)。独立回放用于提交边界、
序列化和确定性风险，不作为每次小修复的固定套餐。明确记录所用规则、输入与验证边界。

编译、整场和全量回归串行运行，持有 `/tmp/hsr-v8-validation.lock`；记录耗时和可取得的峰值内存。
普通检查已回答本次风险且通过后停止，不反复运行同一路线。
新调试输出格式按当前版本验证，旧归档文件保留，不要求跨版本回放兼容。
需要 `RuntimeSourceAuditor` 的会话显式使用 `BattleSession(..., diagnostics="full")`；
普通产品路径默认 `compact`，公共接口回归同时检查两种模式。

## 历史入口

历史 `tools/validate_*` 只有仍被生产、测试或当前任务引用时才承担现行职责；
删除前核对调用者，不因为文件名带阶段编号就直接删除。当前不按旧阶段补验证器。
2026-11-12 已移除 221 个无现行引用的工具模块，保留测试及 CI 引用闭包内的 23 个。
删除的工具、v7/model-pack、旧 HTML 和无现行引用的报告可从 `c3b3483` 的 Git 历史读取。
整理前的完整命令和历史断言见
[历史测试记录](../docs/archive/usage/TEST_COMMANDS_PRE_REFRESH_2026-11-12.md)。

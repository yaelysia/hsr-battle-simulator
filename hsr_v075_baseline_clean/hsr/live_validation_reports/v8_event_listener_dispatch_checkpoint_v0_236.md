# v8 v0_236 事件监听与触发分发核心检查点

## 范围

- 新增 `EventDispatchSystem`，作为 action window、status callback、blocked listener 的统一 runtime 分发入口。
- `CombatExecutor` 的 action trigger window 改为发布 `GameEvent` 后通过 dispatcher 调度，不再直接调用 `TriggerSystem`。
- `BreakSystem` 的 break status `OnStack` 回调改为通过 dispatcher 调度，不再直接调用 `StatusCallbackSystem`。
- `DamageSystem` 为 direct、break、super-break、true damage、hp loss 统一产出 `damage.hit` 事件。
- `ToughnessSystem` 为 executable 削韧产出 `toughness.hit` 事件。
- 多目标命中 transition 现在包含 `current_hit_target_id` 等 per-hit payload；per-hit listener admission 仍标记 partial。

## 当前可信范围

- status-local callback 可通过 `EventDispatchSystem` 进入既有 executable callback/effect 路径，并保持 source audit、settlement traceability、snapshot replay。
- action window trigger 统一由 dispatcher 调度，旧 `TriggerSystem` 只保留为底层执行器。
- blocked global / being-hit / per-hit listener 可以产生 process-only dispatch/listener records，且不污染 state。
- AOE / blast 当前仍是 structural-only 数值范围，但已经具备 per-hit event context。

## 仍不纳入本阶段

- global listener、being-hit listener、per-hit trigger 尚未 admission 为可执行 mutation 路径。
- 队列插队、完整追击、反击、敌人 AI、bounce RNG 仍未实现。
- 本阶段不改变 v0_235 韧性、普通击破、break DOT、super-break 的可信范围。

## 验证

运行目录：`hsr_v075_baseline_clean/hsr`

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_235 --output-dir /tmp/hsr_v8_regression_v0_235
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_236 --output-dir /tmp/hsr_v8_v0_236
git diff --check
```

结果：全部通过。

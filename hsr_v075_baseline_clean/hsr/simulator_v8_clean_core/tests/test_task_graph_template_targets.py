"""Template entity lists remain separate from the current per-hit target."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simulator_v8_clean_core.core.model import BattleState
from simulator_v8_clean_core.systems.task_graph import (
    TaskGraphContinuation, TaskGraphExecutionContext, TaskGraphExecutionHooks,
    TaskGraphExecutor, TaskGraphLeafResult, TaskGraphTargetResult,
    TaskGraphSettlementRecord, TaskGraphTemplateBindingsResult,
)
from simulator_v8_clean_core.tools.validate_p9_s8b2_atomic_executor_core import _graph


def test_template_target_binding_inheritance_empty_shadow_and_continuation():
    graph = _graph("template-targets", {
        "outer": {"kind": "template_call", "refs": (("template", "outer"), ("target", "list")),
                  "branches": (("template_body", "outer", ("scope",)),)},
        "scope": {"kind": "target_scope", "branches": (("target_scope", "", ("inner", "empty", "after")),)},
        "inner": {"kind": "template_call", "refs": (("template", "inner"),),
                  "branches": (("template_body", "inner", ("inherited",)),)},
        "empty": {"kind": "template_call", "refs": (("template", "empty"), ("target", "empty-list")),
                  "branches": (("template_body", "empty", ("empty-leaf",)),)},
        **{name: {"kind": "leaf"} for name in ("inherited", "empty-leaf", "after", "outside")},
    }, ("outer", "outside"))
    observed, resolutions = [], []

    def targets(request, _state):
        resolutions.append(request.formal_task_id)
        return TaskGraphTargetResult("resolved", {
            "task:outer": ("a", "b"), "task:scope": ("a",), "task:empty": (),
        }[request.formal_task_id])

    def leaf(request, _state):
        child = TaskGraphContinuation.from_hook_request(request).child_context("child")
        assert child.template_target_ids == request.template_target_ids
        observed.append((request.formal_task_id, request.target_ids, request.template_target_ids))
        return TaskGraphLeafResult("resolved")

    result = TaskGraphExecutor().execute(BattleState(), graph, TaskGraphExecutionContext("test"),
        TaskGraphExecutionHooks(targets=targets, leaf=leaf))
    assert result.ok, result.errors
    assert resolutions == ["task:outer", "task:scope", "task:empty"]
    assert observed == [
        ("task:inherited", ("a",), ("a", "b")),
        ("task:empty-leaf", ("a",), ()),
        ("task:after", ("a",), ("a", "b")),
        ("task:outside", (), None),
    ]


def test_consumed_template_body_skips_children_and_keeps_domain_acknowledgement():
    graph = _graph("consumed-template", {
        "include": {"kind": "template_call", "refs": (("template", "consumed"),),
                    "branches": (("template_body", "consumed", ("duplicate",)),)},
        "duplicate": {"kind": "leaf"}, "after": {"kind": "leaf"},
    }, ("include", "after"))
    observed = []
    record = TaskGraphSettlementRecord("template_already_applied", "domain_fixture", process_only=True)

    def leaf(request, _state):
        observed.append(request.formal_task_id)
        return TaskGraphLeafResult("resolved")

    result = TaskGraphExecutor().execute(BattleState(), graph, TaskGraphExecutionContext("test"),
        TaskGraphExecutionHooks(leaf=leaf, template_bindings=lambda *_: TaskGraphTemplateBindingsResult(
            "resolved", body_consumption_record=record)))
    assert result.ok, result.errors
    assert observed == ["task:after"]
    assert record in result.settlement_records


def test_template_entity_fetch_keeps_the_full_template_list_inside_single_target_scope():
    from hsr.simulator_v8_clean_core.core.model import BattleState, UnitState
    from hsr.simulator_v8_clean_core.rules.ir import CanonicalIR, IRSource
    from hsr.simulator_v8_clean_core.rules.rulebook import RuleBook
    from hsr.simulator_v8_clean_core.systems.target import TargetSystem
    from hsr.simulator_v8_clean_core.systems.unit_relation import TargetEvaluationContext
    from hsr.simulator_v8_clean_core.tbgd.lowering import _target_expression_from_raw

    source = IRSource("validation_fixture/template", "TargetExpression", "template", {"json_path": "$"})
    expression = _target_expression_from_raw({"$type": "RPG.GameCore.TargetFetchTemplateEntityList"},
        field_name="$self", expression_id="template", source=source)
    assert expression.coverage_status == "executable", expression.blocked_reason
    state = BattleState(units={identity: UnitState(identity, "ally", "fixture") for identity in ("a", "b")})
    system = TargetSystem(RuleBook(CanonicalIR("validation")))
    context = TargetEvaluationContext("a", parameter_entity_ids=("a",), template_entity_ids=("a", "b"))
    assert system.resolve_target_expression(state, expression, context=context.with_parameter("b")).target_ids == ("a", "b")
    assert system.resolve_target_expression(state, expression,
        context=TargetEvaluationContext("a", template_entity_ids=())).target_ids == ()
    assert system.resolve_target_expression(state, expression,
        context=TargetEvaluationContext("a")).blocked_reason == "target_template_parameters_missing"

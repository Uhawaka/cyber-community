"""Model adapters for independently executable literary skill stages."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Mapping

from engine.adapters.model_json import decode_json_object
from engine.adapters.model_literary_schema import (
    decode_draft as _decode_draft,
    writing_facts as _writing_facts,
)
from engine.contracts import (
    EditorialBrief,
    EditorialDiagnostic,
    SourcedDraft,
    TextModel,
)
from engine.narrative.planning import NarrativeRenderRequest
from engine.narrative.skills import get_literary_skill, get_world_voice


class ModelLiteraryStageRunner:
    def __init__(
        self,
        model: TextModel,
        *,
        timeout_seconds: float,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.labels = dict(labels or {})
        self.diagnostics: list[EditorialDiagnostic] = []
        self.artifacts: dict[str, object] = {}

    def develop(
        self,
        skill_id: str,
        request: NarrativeRenderRequest,
        facts: list[dict[str, object]],
        plan: dict[str, object],
    ) -> EditorialBrief:
        prompt = (
            self._header(skill_id)
            + _style_instruction(request)
            + "只返回 editorial-brief/v1 JSON：focus、goal、conflict、stakes、"
            "turn_source_id、selected_source_ids、direct_quote_source_ids、"
            "ending_source_id、ending_fact_relation。来源编号必须来自事实且保持"
            "顺序；selected_source_ids 最多八个，direct_quote_source_ids 最多"
            "两个。不得写正文。计划："
            + _json(plan)
            + "事实："
            + _json(facts)
        )
        raw = self._complete(skill_id, prompt)
        available = [str(item["source_event_id"]) for item in facts]
        selected = _ordered_ids(
            raw.get("selected_source_ids"), available, maximum=8
        )
        required = [
            str(item["source_event_id"])
            for item in facts
            if item["kind"] in {"incident_occurred", "user_intervention"}
        ]
        resolved_fact = next(
            (
                item
                for item in reversed(facts)
                if (
                    item["kind"] == "turn_resolved"
                    and isinstance(item.get("authorized_context"), dict)
                    and item["authorized_context"].get("dramatic_progress")
                    == "resolved"
                    and item["authorized_context"].get("scene_outcome")
                )
            ),
            None,
        )
        resolved_id = (
            str(resolved_fact["source_event_id"])
            if resolved_fact is not None
            else None
        )
        resolved_outcome = (
            str(resolved_fact["authorized_context"]["scene_outcome"])
            if resolved_fact is not None
            else None
        )
        decision_sources = (
            _collective_decision_sources(facts)
            if resolved_fact is not None
            else ()
        )
        turn_id = _known_id(
            raw.get("turn_source_id"),
            available,
            fallback=plan.get("turning_point_source_id"),
        )
        ending_id = _known_id(
            raw.get("ending_source_id"),
            available,
            fallback=(
                plan.get("outcome_source_ids", [])[-1]
                if plan.get("outcome_source_ids")
                else turn_id
            ),
        )
        selected = _select_with_required(
            available,
            selected,
            [
                *required,
                *decision_sources,
                turn_id,
                resolved_id,
                ending_id,
            ],
            maximum=8,
        )
        selected = _prune_superseded_turns(
            selected,
            facts,
            required_ids={
                item
                for item in (turn_id, resolved_id, ending_id)
                if item is not None
            },
        )
        if not selected or turn_id is None or ending_id is None:
            raise ValueError("developmental editor omitted required sources")
        quote_ids = tuple(
            source_id
            for source_id in _ordered_ids(
                raw.get("direct_quote_source_ids"), available, maximum=2
            )
            if source_id in selected
        )
        brief = EditorialBrief(
            focus=_text(raw.get("focus"), request.plan.focus_character_id or ""),
            goal=_text(raw.get("goal"), request.plan.scene_goal or ""),
            conflict=_text(raw.get("conflict"), "来源中的现实阻力"),
            stakes=_text(raw.get("stakes"), "拖延将使现有风险继续"),
            turn_source_id=turn_id,
            selected_source_ids=selected,
            direct_quote_source_ids=quote_ids,
            ending_source_id=ending_id,
            ending_fact_relation=_text(
                raw.get("ending_fact_relation"), "决定已经形成，局势随之改变"
            )[:80],
            resolved_outcome=resolved_outcome,
        )
        self.artifacts["developmental_edit"] = asdict(brief)
        return brief

    def draft(
        self,
        skill_id: str,
        request: NarrativeRenderRequest,
        brief: EditorialBrief,
        facts: list[dict[str, object]],
        scene_lore: list[str],
    ) -> SourcedDraft:
        voice = get_world_voice(request.style.voice_id)
        selected = set(brief.selected_source_ids)
        quote_ids = set(brief.direct_quote_source_ids)
        writing_facts = _writing_facts(
            facts,
            selected_source_ids=selected,
            direct_quote_source_ids=quote_ids,
        )
        prompt = (
            self._header(skill_id)
            + voice.model_instruction(
                request.plan.focus_character_id,
                request.style.character_voice_registers,
            )
            + _style_instruction(request)
            + "只返回 sourced-draft/v1 JSON，字段 title、paragraphs；每个段落"
            "只有 source_event_ids 与 text。写成三至五段，编号必须来自事实并"
            "按全局时序递增。人物、行动结果、台词、心理、因果和环境不得超出"
            "来源。发展编辑简报："
            + _json(asdict(brief))
            + "事实："
            + _json(writing_facts)
            + "场景资料："
            + _json(scene_lore)
            + "实体显示名："
            + _json(self.labels)
        )
        available_ids = tuple(
            str(item["source_event_id"]) for item in writing_facts
        )
        try:
            result = _decode_draft(
                self._complete(skill_id, prompt),
                available_ids,
            )
        except ValueError as exc:
            result = _decode_draft(
                self._complete(
                    skill_id,
                    prompt
                    + "\n结构重试："
                    + str(exc)
                    + "。每一段来源必须是source_order中的连续前进区间；"
                    "后段不得引用早于前段最后来源的编号。",
                ),
                available_ids,
            )
        covered = {
            source_id
            for paragraph in result.paragraphs
            for source_id in paragraph.source_event_ids
        }
        missing = set(brief.selected_source_ids) - covered
        if missing:
            result = _decode_draft(
                self._complete(
                    skill_id,
                    prompt
                    + "\n覆盖重试：上一稿遗漏了"
                    + ",".join(sorted(missing))
                    + "。必须在保持全局时序的前提下，把每个遗漏来源并入"
                    "承担相应事实的段落；可以压缩，不得省略来源编号。",
                ),
                available_ids,
            )
            covered = {
                source_id
                for paragraph in result.paragraphs
                for source_id in paragraph.source_event_ids
            }
            missing = set(brief.selected_source_ids) - covered
            if missing:
                raise ValueError(
                    "scene writer omitted selected sources: "
                    + ",".join(sorted(missing))
                )
        self.artifacts["scene_draft"] = _draft_record(result)
        return result

    def revise(
        self,
        skill_id: str,
        request: NarrativeRenderRequest,
        draft: SourcedDraft,
        brief: EditorialBrief,
        facts: list[dict[str, object]],
        scene_lore: list[str],
        *,
        diagnostic: str = "",
    ) -> SourcedDraft:
        voice_instruction = ""
        if get_literary_skill(skill_id).stage == "line_edit":
            voice_instruction = get_world_voice(
                request.style.voice_id
            ).model_instruction(
                request.plan.focus_character_id,
                request.style.character_voice_registers,
            )
        prompt = (
            self._header(skill_id)
            + voice_instruction
            + _style_instruction(request)
            + "只返回 sourced-draft/v1 JSON，字段 title、paragraphs；每段只有"
            " source_event_ids 与 text。不得增加、删除或重排段落来源编号。"
            + (f"上轮门禁诊断：{diagnostic}。" if diagnostic else "")
            + "发展编辑简报："
            + _json(asdict(brief))
            + "候选稿："
            + _json(_draft_record(draft))
            + "事实："
            + _json(
                _writing_facts(
                    facts,
                    selected_source_ids=set(brief.selected_source_ids),
                    direct_quote_source_ids=set(
                        brief.direct_quote_source_ids
                    ),
                )
            )
            + "场景资料："
            + _json(scene_lore)
        )
        available_ids = tuple(
            source_id
            for paragraph in draft.paragraphs
            for source_id in paragraph.source_event_ids
        )
        try:
            result = _decode_draft(
                self._complete(skill_id, prompt),
                available_ids,
            )
        except ValueError as exc:
            result = _decode_draft(
                self._complete(
                    skill_id,
                    prompt
                    + "\n结构重试："
                    + str(exc)
                    + "。保持每段原有来源编号，且所有段落全局只向后推进。",
                ),
                available_ids,
            )
        if tuple(
            item.source_event_ids for item in result.paragraphs
        ) != tuple(item.source_event_ids for item in draft.paragraphs):
            raise ValueError(f"{skill_id} changed paragraph provenance")
        self.artifacts[get_literary_skill(skill_id).stage] = _draft_record(result)
        return result

    def _header(self, skill_id: str) -> str:
        skill = get_literary_skill(skill_id)
        return (
            f"执行宿主文学 Skill {skill.skill_id} v{skill.version}，"
            f"阶段={skill.stage}。以下 SKILL.md 是方法契约：\n"
            f"{skill.instruction}\n"
        )

    def _complete(self, skill_id: str, prompt: str) -> dict[str, object]:
        skill = get_literary_skill(skill_id)
        started = time.monotonic()
        try:
            raw = self.model.complete(
                prompt, timeout_seconds=self.timeout_seconds
            )
            decoded = decode_json_object(raw)
            if not isinstance(decoded, dict):
                raise ValueError("skill response is not an object")
        except BaseException as exc:
            self.diagnostics.append(
                EditorialDiagnostic(
                    skill_id,
                    skill.stage,
                    "failed",
                    int((time.monotonic() - started) * 1000),
                    f"{type(exc).__name__}: {str(exc)[:300]}",
                )
            )
            raise
        self.diagnostics.append(
            EditorialDiagnostic(
                skill_id,
                skill.stage,
                "ok",
                int((time.monotonic() - started) * 1000),
            )
        )
        return decoded


def _style_instruction(request: NarrativeRenderRequest) -> str:
    style = request.style
    return (
        f"语言={style.language}；视角={style.point_of_view}；"
        f"叙述距离={style.narrative_distance}；语体={style.register}；"
        f"节奏={style.rhythm}；对话密度={style.dialogue_density}；"
        f"意象域={list(style.imagery_domains)}；"
        f"禁用表达={list(style.forbidden_phrases)}；"
        f"叙事功能关注={list(style.narrative_functions)}；"
        f"质量维度={list(style.quality_dimensions)}。"
        "叙事功能只用于检查现有来源，不授权补写来源中没有的证据。"
    )


def _known_id(
    value: object,
    available: list[str],
    *,
    fallback: object,
) -> str | None:
    if isinstance(value, str) and value in available:
        return value
    return fallback if isinstance(fallback, str) and fallback in available else None


def _ordered_ids(
    value: object, available: list[str], *, maximum: int
) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    selected = {
        item for item in value if isinstance(item, str) and item in available
    }
    return tuple(item for item in available if item in selected)[:maximum]


def _select_with_required(
    available: list[str],
    optional: tuple[str, ...],
    required: list[object],
    *,
    maximum: int,
) -> tuple[str, ...]:
    mandatory = {
        item
        for item in required
        if isinstance(item, str) and item in available
    }
    if len(mandatory) > maximum:
        raise ValueError("required literary sources exceed stage budget")
    selected = set(mandatory)
    for item in optional:
        if len(selected) == maximum:
            break
        selected.add(item)
    return tuple(item for item in available if item in selected)[:maximum]


def _collective_decision_sources(
    facts: list[dict[str, object]],
    *,
    maximum_actors: int = 4,
) -> tuple[str, ...]:
    """Keep one committed decision beat per participant in a resolved scene."""

    by_actor: dict[str, str] = {}
    for fact in facts:
        context = fact.get("authorized_context")
        decision = (
            context.get("decision")
            if isinstance(context, dict)
            else None
        )
        actor_id = fact.get("actor_id")
        if (
            fact.get("kind") == "turn_resolved"
            and isinstance(actor_id, str)
            and actor_id
            and isinstance(decision, str)
            and decision.strip()
        ):
            by_actor[actor_id] = str(fact["source_event_id"])
    return tuple(by_actor.values())[-maximum_actors:]


def _prune_superseded_turns(
    selected: tuple[str, ...],
    facts: list[dict[str, object]],
    *,
    required_ids: set[str],
) -> tuple[str, ...]:
    """Drop an earlier turn when the same actor later commits more strongly."""

    by_id = {str(item["source_event_id"]): item for item in facts}
    kept: list[str] = []
    for index, source_id in enumerate(selected):
        fact = by_id[source_id]
        context = fact.get("authorized_context")
        progress = (
            context.get("dramatic_progress")
            if isinstance(context, dict)
            else None
        )
        actor = fact.get("actor_id")
        superseded = any(
            later.get("kind") == "turn_resolved"
            and later.get("actor_id") == actor
            and isinstance(later.get("authorized_context"), dict)
            and later["authorized_context"].get("dramatic_progress")
            in {"decision", "resolved"}
            for later_id in selected[index + 1 :]
            for later in (by_id[later_id],)
        )
        if (
            source_id not in required_ids
            and fact.get("kind") == "turn_resolved"
            and progress in {"none", "decision"}
            and superseded
        ):
            continue
        kept.append(source_id)
    return tuple(kept)


def _text(value: object, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _draft_record(value: SourcedDraft) -> dict[str, object]:
    return {
        "title": value.title,
        "paragraphs": [
            {
                "source_event_ids": list(item.source_event_ids),
                "text": item.text,
            }
            for item in value.paragraphs
        ],
    }


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)

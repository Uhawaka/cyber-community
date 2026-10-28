"""One bounded model decision from owned, source-labelled context."""

from __future__ import annotations

from dataclasses import asdict
import json
import math
from hashlib import sha256

from engine.contracts.community import ActionProposal, ActionVerb, IntentStep
from engine.contracts.intent import INTENT_STEP_VERBS, ready_intent_steps
from engine.runtime.character.community_context import decision_source_refs, resolve_visible_claim_refs

MAX_MODEL_PROMPT_BYTES = 131072


class ModelCommunityPolicy:
    records_model_attempts = True
    version = "community-model-policy/v20"

    def __init__(self, model, *, timeout_seconds=10.0, max_requests=1000):
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 600
                or isinstance(max_requests, bool) or not isinstance(max_requests, int)
                or not 0 <= max_requests <= 100000):
            raise ValueError("invalid community model budget")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_requests = max_requests
        self.requests = 0

    def for_run(self):
        return ModelCommunityPolicy(self.model, timeout_seconds=self.timeout_seconds, max_requests=self.max_requests)

    def managed_identity(self):
        from engine.adapters.openai_compatible import OpenAICompatibleTextModel
        if type(self.model) is OpenAICompatibleTextModel:
            model = self.model
            values = {"provider": model.provider, "model": model.model, "temperature": model.temperature,
                      "max_tokens": model.max_tokens,
                      "endpoint_sha256": sha256(model.base_url.encode()).hexdigest(), "transport_attempts": 1}
        else:
            identity = getattr(self.model, "community_identity", None)
            if not isinstance(identity, str) or not identity.strip() or len(identity) > 2000:
                raise ValueError("custom managed model must declare community_identity")
            values = {"implementation": f"{type(self.model).__module__}.{type(self.model).__qualname__}",
                      "identity": identity}
        return sha256(json.dumps(values, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def propose(self, context):
        if self.requests >= self.max_requests:
            raise RuntimeError("community model request budget exhausted")
        self.requests += 1
        prompt = (
            "你只决定自己的行为，不替其他角色作决定，不宣称预期效果已经发生。\n"
            "根据自己的欲望、经历和眼前条件提出一个行动，可以等待、休息或组合已有能力。\n"
            "只返回 JSON，字段 verb,target_id,intent,source_refs，可选 quantity,item_id,speech,reply_to,requested_item_id,requested_quantity。\n"
            "也可以返回 intent_kind=navigate,target_id=已知目的地,intent,source_refs；仅编译眼前一步，后续由你重新决定。\n"
            "intent_kind=navigate_plan 使用同样字段，将已知路线编为至多八步个人计划；后续仍须逐步选择并裁决。\n"
            "可以返回 intent_kind=plan,intent,source_refs,steps，可选 goal_id（本人活跃目标）、deadline_tick（当前或未来的复查时间）和 budget（[资源id,取出上限]数组）；steps 为1至8个对象，每个含 verb,target_id，可选 quantity,speech,on_failure（失败后可选择跳转的后续步骤索引）。计划不是事实，不替他人同意。\n"
            "计划步骤支持的动作：" + ",".join(sorted(INTENT_STEP_VERBS)) + "。\n"
            "rest/wait 的目标必须是本人；speak 必须填写 speech；只有 take/use 可指定大于1的 quantity。其他已注册行动可直接选择，不能作为计划步骤。\n"
            "use 只能消耗本人 inventory 中已持有的物品；现场可见不等于持有，可先选择 take。take 的 available_quantity 是现场数量，use 的是本人持有数量；零表示当前无可用数量。\n"
            "步骤可选 depends_on 数组，表示必须真实完成的步骤索引，空数组表示无依赖；省略则按顺序等待此前步骤完成或被本人跳过。不得循环依赖。\n"
            "步骤可选 guards 数组，条件为 {kind:at_location,target_id:地点} 或 {kind:inventory_at_least,target_id:物品,quantity:数量}，只检查本人位置和库存。条件在尝试时重查，失败阻塞计划，不预留资源。\n"
            "非空 budget 限制关联步骤累计提取，未列资源额度为零；它不是预留，失败时已消耗材料不返还。\n"
            "intent_plans 是本人的计划；只有自己再返回 intent_kind=continue_plan,plan_id,intent,source_refs 才尝试步骤，可选 step_index 选择依赖已完成的步骤；失败阻塞时只能重试被阻塞步骤。步骤仍经行动裁决。\n"
            "intent_plan_history 是本人最近的已完成或放弃计划，可引用其 source_refs 创建替代计划；放弃受阻计划时可引用其失败来源，避免丢失原因。历史不是新行动，也不代表目标已完成。\n"
            "plan_review_inputs 是本人观察到的、对象与未完成计划步骤有关的近期事件线索，依次为计划id、事件来源、类型、行动者、目标、可见内容（可能截断）；相关不等于事实成立或他人同意。你可自行复查、继续或放弃。\n"
            "超过 deadline_tick 的未完成计划会在活动结算后请求一次复查，deadline_reached 表示已提示；你可自主继续、分支或放弃，不会自动完成或取消活动。\n"
            "也可返回 verb=abandon_plan,target_id=自己的plan_id,intent,source_refs 放弃未完成计划，不改变世界事实。\n"
            "阻塞计划有失败分支时，可返回 verb=branch_plan,target_id=自己的plan_id,intent,source_refs 主动选择该分支。\n"
            "pursue 的 item_id 是完成动作 repair/take/learn/move/speak，quantity 是目标量；abandon 的 target_id 是自身 goal_id。\n"
            "speak 可用 item_id 转述自身 claim_id；offer/transfer 的 item_id 是自身物品，可指定 requested_item_id/quantity 作交换。\n"
            "accept/reject 的 target_id 是收到的 offer_id 或 commitment_id。commit 的 item_id 是承诺目标，reply_to 是 repair/transfer/speak。\n"
            "request 向眼前 helper 的 target_id 请求维修材料，item_id 是材料，reply_to 是已知维修设备，quantity 是所需数量；reject 可拒绝收到的 request_id。\n"
            "请求不代表对方同意。repair 优先消耗自己的材料，不足部分才消耗现场库存。\n"
            "可以按自己的需要、计划与已接受承诺保留材料、提出交换条件或拒绝；这些是个人选择，不是强制库存锁。\n"
            "known_repair_costs 是自己已观察设备的已知维修成本，不表示远处设备状态或当前材料库存。\n"
            "可主动 commit 给眼前受益人：reply_to=repair、item_id=设备、quantity=承诺达到的 condition，期限为 24 Tick。\n"
            "提案不扣维修材料、不是对方同意；只有对方 accept 后才成为约定，实际维修完成才能履约。\n"
            "可按个人能力、物资、时长与已接受义务选择是否承诺；reserved 是眼前设备占用，commitment_history 是本人知情的终态约定。\n"
            "handoff 的 target_id 是眼前接任者，item_id 是自己照管的当地设备；对方 accept/reject 的 target_id 是 handoff_id。\n"
            "交接答复期限为 24 Tick，只有有维修能力的接任者独立接受才转移照管职责；拒绝或到期不改变职责。\n"
            "职责转移不转移材料、组织权限或既有承诺，也不代表劳动已完成。handoffs/handoff_history 只含自己知情的记录。\n"
            "capabilities 是自己可知的有来源能力声明；本人的初始技能与完成学习可作为自知，别人的声明只是听闻，不是实际技能或同意。\n"
            "可 speak 用本人能力 claim_id 表达能力，但表达不等于承诺；maintenance_requirements 只含眼前设备的注册维修要求。\n"
            "可以按本人兴趣、前置技能、负荷与期限选择 learn 或准备接任；真实学习完成才获得技能，学习不会自动接受交接。\n"
            "可按自己的兴趣先 rest 再重新判断交接，休息不承诺接任、不延长期限，之后仍可以拒绝。\n"
            "organization_groups 仅列本人在组织现场可见的成员小组；speak 的 target_id 可为该 organization_id。\n"
            "invitation_groups 包含本人在现场的组织及可见现场成员，即使只有本人在场也可邀请现场非成员；它不是群体发言参与者列表。\n"
            "relationships 是本人的主观信任，trust_sources 是每个对象最近一次本人可见的信任变化来源，不代表该事件单独决定全部信任。\n"
            "面向小组表达只记录自己的话，不替成员答复、同意或承担义务；同地旁人按实际听觉获知，远处成员不会自动收到。\n"
            "record 的 target_id 是现场所属组织，item_id 是自己持有的完整 claim_id；归档不改事实，也不让其他成员自动知道内容。\n"
            "organization_records 仅含可访问档案元数据，不是已读知识；read 的 target_id 是组织、item_id 是 record_id。\n"
            "必须本人在组织现场 read 才形成有作者来源的听闻；阅读不授予技能、职责、同意或新的有效期限。\n"
            "lend 向眼前 borrower 的 target_id 提议借出本人材料，item_id/quantity 是本金，requested_quantity 是同物品偿还量（省略则等于本金）。\n"
            "loans 只含本人参与的未决债务，期限为提案后24 Tick；borrower 独立 accept/reject，accept 才转移本金。\n"
            "loaned_requests 只列本人已针对该未决材料请求提出过借贷的 request_id，不代表借款人已经接受。\n"
            "repay 的 target_id 是本人借款的 loan_id，须双方现场且本人库存足够；逾期不自动扣款、不抹除债务，后来仍可主动偿还。\n"
            "resign 的 target_id 是本人当前所属的现场组织；退出只撤销成员权限，不删除本人材料、记忆、照管职责、债务或已接受承诺。\n"
            "invite 的 target_id 是本人所属现场组织，item_id 是现场非成员；邀请仅表示邀请人自己的选择，不代表全体成员投票。\n"
            "membership_invitations 只列本人收到且当前可用的邀请；join 的 target_id 是组织、reply_to 是邀请事件序号，source_refs 须包含该 event 来源。本人独立决定是否加入。\n"
            "organization_roles 只含现场本人组织的岗位登记、所需技能与权限；take_role/leave_role 的 target_id 是组织、item_id 是岗位。\n"
            "organization_seats 是本人所属全部组织登记的岗位、所在地与现任，可用于决定是否前往接任本人有真实技能的空缺岗位。\n"
            "只能本人有真实技能时接任空缺岗位，或本人主动卸任；岗位不授予技能、材料、个人照管职责或替人同意，退出组织会空出本人岗位。\n"
            "censure 的 target_id 是组织、item_id 是现场成员、quantity 是规范序号从1开始、reply_to 是自己可见的真实旧事件序号。\n"
            "censure 必须持有当前岗位的censure权限并引用该event来源；speech 是本人的告诫判断，不是客观定罪，不收缴、驱逐或删除债务。\n"
            "lease 的 target_id 是现场承租人、item_id 是本人持有的可携带不可消费物品、quantity 是数量、requested_quantity 是租期Tick（默认24，最多100）。\n"
            "lessee 必须独立accept，租期从接受开始；return_lease 的target_id是本人租约，真实持有物品才能归还。到期不自动收缴，晚还先记录overdue。\n"
            "source_refs 必须从 allowed_source_refs 中选择真实来源；声明编号不是来源，不得编造世界知识。\n"
            "输入：\n" + json.dumps({**asdict(context), "allowed_source_refs": sorted(decision_source_refs(context))},
                                  ensure_ascii=False)
        )
        if len(prompt.encode("utf-8")) > MAX_MODEL_PROMPT_BYTES:
            raise ValueError("model input exceeds decision budget")
        from engine.adapters.openai_compatible import OpenAICompatibleTextModel
        complete = self.model.complete_once if type(self.model) is OpenAICompatibleTextModel else self.model.complete
        answer = complete(prompt, timeout_seconds=self.timeout_seconds)
        if not isinstance(answer, str) or len(answer) > 8000:
            raise ValueError("model response exceeds decision budget")
        try:
            raw = json.loads(answer)
        except RecursionError as exc:
            raise ValueError("model decision nesting exceeds budget") from exc
        if isinstance(raw, dict) and "source_refs" in raw:
            raw["source_refs"] = resolve_visible_claim_refs(context, raw["source_refs"])
        if isinstance(raw, dict) and "intent_kind" in raw:
            kind = raw["intent_kind"]
            if not isinstance(raw.get("source_refs"), list):
                raise ValueError("invalid structured intention")
            if kind in ("navigate", "navigate_plan") and set(raw) == {"intent_kind", "target_id", "intent", "source_refs"}:
                from engine.runtime.character.community_intents import compile_navigation, compile_navigation_plan
                compiler = compile_navigation if kind == "navigate" else compile_navigation_plan
                return compiler(context, raw["target_id"], raw["intent"], raw["source_refs"])
            if (kind == "plan"
                    and {"intent_kind", "intent", "source_refs", "steps"} <= set(raw)
                    and set(raw) <= {"intent_kind", "intent", "source_refs", "steps", "budget", "goal_id", "deadline_tick"}):
                if not isinstance(raw["steps"], list) or not 1 <= len(raw["steps"]) <= 8:
                    raise ValueError("invalid structured plan steps")
                try:
                    steps = tuple(IntentStep(**step) for step in raw["steps"])
                except (TypeError, ValueError) as exc:
                    raise ValueError("invalid structured plan steps") from exc
                return ActionProposal(
                    f"decision:{context.actor_id}:{context.perception.tick}", context.actor_id,
                    ActionVerb.PLAN, context.actor_id, raw["intent"], tuple(raw["source_refs"]),
                    context.state_hash, plan_steps=steps, plan_budget=raw.get("budget", ()),
                    plan_goal_id=raw.get("goal_id", ""), plan_deadline_tick=raw.get("deadline_tick"),
                )
            if kind == "continue_plan" and set(raw) in (
                {"intent_kind", "plan_id", "intent", "source_refs"},
                {"intent_kind", "plan_id", "intent", "source_refs", "step_index"},
            ):
                plan = next((p for p in context.intent_plans if p.plan_id == raw["plan_id"]), None)
                if plan is None or plan.owner_id != context.actor_id or plan.status not in {"ready", "blocked"}:
                    raise ValueError("personal plan is unavailable")
                index = raw.get("step_index", plan.cursor)
                if (isinstance(index, bool) or not isinstance(index, int)
                        or index not in (ready_intent_steps(plan) if plan.status == "ready" else (plan.cursor,))):
                    raise ValueError("plan step dependencies are not satisfied")
                step = plan.steps[index]
                return ActionProposal(
                    f"decision:{context.actor_id}:{context.perception.tick}", context.actor_id,
                    ActionVerb(step.verb), step.target_id, raw["intent"], tuple(raw["source_refs"]),
                    context.state_hash, quantity=step.quantity, item_id=step.item_id, speech=step.speech,
                    intent_plan_id=plan.plan_id, intent_step_index=index,
                )
            raise ValueError("invalid structured intention")
        allowed = {"verb", "target_id", "intent", "source_refs", "quantity", "item_id", "speech", "reply_to",
                   "requested_item_id", "requested_quantity"}
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError("model decision has unknown fields")
        if not {"verb", "target_id", "intent", "source_refs"} <= set(raw):
            raise ValueError("model decision is missing required fields")
        if not isinstance(raw.get("source_refs"), list):
            raise ValueError("model decision needs source_refs")
        return ActionProposal(
            f"decision:{context.actor_id}:{context.perception.tick}", context.actor_id,
            ActionVerb(raw["verb"]), raw["target_id"], raw["intent"],
            tuple(raw["source_refs"]), context.state_hash, raw.get("quantity", 1),
            raw.get("item_id", ""), raw.get("speech", ""), raw.get("reply_to", ""),
            raw.get("requested_item_id", ""), raw.get("requested_quantity", 0),
        )

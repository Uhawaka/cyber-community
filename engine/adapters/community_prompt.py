"""决定提示词：先给判断顺序，再给动作参数，机制细则压到最后。

原来的提示词是一堵 60 行的机制墙，模型只挑得到最简单的五个动作（speak/take/inspect/
repair/move），`offer/accept/reject/handoff` 一次没用过、`refuse` 一次没出现。
这一版把常用动作放到前面、给一个 JSON 例子、明说拒绝是正当的，把计划与组织压成短行。
被测试引用过的句子逐字保留。
"""

from __future__ import annotations

import json

from engine.contracts.intent import INTENT_STEP_VERBS


def decision_prompt(window) -> str:
    payload = json.dumps(window, ensure_ascii=False)
    verbs = _window_verbs(window)
    lines = [
        "你只决定自己这一 Tick 做什么，不替其他角色决定，也不宣称预期效果已经发生。\n",
        "只返回 JSON；下面先说这一轮该看什么，再说动作怎么写，最后是少用的机制。\n",
        "\n【先看这四处，再决定】\n",
        "private_knowledge 是本人自己知道而没公开的事（secret）与本人相信但未必为真的事（belief）："
        "可以说、隐瞒或试探着问；说出口就进入事实，听的人会记住，收不回。belief 不是已核实的事实。\n",
        "errands 是作者给你安排、必须去别处办的事（物件编号，地点编号，地名）；authored_goals 是长期想办成的事。"
        "那件东西不在眼前也不在手上时 take/inspect/repair 都会失败——先 move 到那个地点，到了才动手。\n",
        "pressing_need 非空时说明你已经憋到一个程度：这一轮优先说一件私事，或去求证你一直没问的事。\n",
        "reachable 是从这里认得的路（路线编号，通向哪里）：要办的事在别处，move 的 target_id 写路线编号，不是地点编号。\n",
        "\n【常用动作：多数时候够用】\n",
        "move —— target_id=路线编号。人不在那里，走过去是唯一办法。\n",
        "take / inspect / repair —— 只对眼前或手里的东西有效。take 看 available_quantity，use 看持有数量，零就是没有。"
        "use 只能消耗本人 inventory 中已持有的物品；现场可见不等于持有，可先 take。\n",
        "speak —— target_id=在场的人或组织，speech=你的原话；可选 speech_act=request/promise/refuse/clarify/inform，"
        "topic_ref 可省略，只在确定对方就在眼前时才填在场的实体或角色编号，填错会被拒。只有 take/use 可指定大于1的 quantity；rest/wait 的目标必须是本人。\n",
        "requests_to_me 是别人亲口求你、你还没回的事（来源, 谁提的, 原话）：可以答应"
        "（speech_act=promise, reply_to=那个来源），也可以拒绝（speech_act=refuse, reply_to=那个来源）。"
        "带上 reply_to 才算正式答复，会落成有期限的义务。\n",
        "拒绝是正当的：做不到、不愿意、对方条件不成立，就直说 refuse，不必用答应来收场——答应下来的事要还。\n",
    ]
    bargain = _bargain_rules(verbs)
    if bargain:
        lines.append("\n【要谈条件、要交接时才用】\n")
        lines.extend(bargain)
    lines.extend((
        "\n【进阶机制：用得少，规则照旧】\n",
        "计划 —— intent_kind=plan 一次编至多八步，steps=[{verb,target_id}]，可选 depends_on、"
        "guards（at_location / inventory_at_least）、budget、goal_id、deadline_tick；接着走用 continue_plan,plan_id。"
        "计划步骤支持的动作：" + ",".join(sorted(INTENT_STEP_VERBS)) + "。\n",
        "计划不是事实、不替他人同意：受阻只能重试被阻塞步骤，可 branch_plan 走失败分支，abandon_plan 放弃。"
        "也可只走一步：intent_kind=navigate,target_id=已知目的地。\n",
        "组织 —— invite/join/resign 管成员，take_role/leave_role 管岗位；record 归档（归档不改事实）；"
        "read 读 organization_records，那只是元数据，不是已读知识。\n",
        "censure 需要当前岗位的权限并引用真实旧事件；lease/return_lease 是租借，期满不自动收缴；transfer 不转移承诺与债务。\n",
        "能力与照管 —— capabilities 是可知的能力声明（别人的只是听闻，不是技能或同意）；"
        "maintenance_requirements 只含眼前设备；学习不会自动接受交接，休息不延长期限。\n",
        "其他可用的还有：learn、pursue、abandon、wait、rest、check 类只读动作；参数按名字直译，都要真实来源。\n",
        "\n【来源与格式】\n",
        "source_refs 必须从 allowed_source_refs 中选择真实来源；声明编号不是来源，不得编造世界知识。\n",
        "输入是索引。loaded 里才是这一轮展开的正文；索引只有名字和编号，不表示正文已经读过。\n",
        "字段：verb,target_id,intent,source_refs，可选 quantity,item_id,speech,reply_to,requested_item_id,requested_quantity。\n",
        "输入：\n",
        payload,
    ))
    return "".join(lines)


def _window_verbs(window) -> set[str]:
    verbs = {item[0] for item in window.get("operations_index", ()) if item}
    verbs.update(item.get("verb", "") for item in window.get("loaded", {}).get("operations", ()))
    for plan in window.get("intent_plans", ()):
        verbs.update(step.get("verb", "") for step in plan.get("steps", ()))
    return verbs


def _bargain_rules(verbs: set[str]) -> list[str]:
    rules = []
    if verbs & {"offer", "accept", "reject"}:
        rules.append(
            "offer —— target_id=对方，item_id=你拿出的东西，requested_item_id/requested_quantity=你要什么；对方 accept 才算数。\n"
        )
        rules.append("accept / reject —— target_id=收到的 offer_id、commitment_id、handoff_id 或 request_id。\n")
    if "request" in verbs:
        rules.append("request —— 向眼前有维修能力的人要材料：item_id=材料，reply_to=设备，quantity=数量；请求不代表对方同意。\n")
    if verbs & {"transfer", "handoff"}:
        rules.append("transfer / handoff —— transfer 转交本人手里的物品；handoff 把照管的设备交给眼前接任者，对方独立 accept 才转移，期限 24 Tick。\n")
    if "commit" in verbs:
        rules.append("commit —— reply_to=repair、item_id=设备、quantity=承诺达到的 condition，期限 24 Tick；提案不扣材料、不是同意，实际修完才履约。\n")
    if verbs & {"lend", "repay"}:
        rules.append("lend / repay —— lend 对眼前借款人，item_id/quantity 是本金，requested_quantity 是偿还量；repay 的 target_id 是本人的 loan_id。\n")
    if rules:
        rules.append(
            '例如：{"verb":"offer","target_id":"mei","item_id":"lamp-oil","requested_item_id":"wire",'
            '"requested_quantity":2,"intent":"拿灯油换两段线","source_refs":["event:12"]}\n'
        )
    return rules

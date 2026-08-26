"""Versioned teaching contracts for formal capability-pack lessons.

The contract is deliberately separate from ``knowledge_point_id``.  Existing
paths, assessments and learner evidence keep their stable point IDs, while a
contract exposes smaller ``concept_id`` and observable ``outcome_id`` values
to generation, resources and audits.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from html import escape
from typing import Any


TEACHING_CONTRACT_VERSION = "teaching-contract-v1"
FORMAL_CONTRACT_REVIEW_STATUS = "structure_validated_pending_expert_review"


def _concept(contract_id: str, suffix: str, title: str, description: str) -> dict[str, str]:
    return {
        "concept_id": f"{contract_id}.{suffix}",
        "title": title,
        "description": description,
    }


def _outcome(
    contract_id: str,
    suffix: str,
    statement: str,
    criteria: str,
    concept_suffixes: list[str],
    block_types: list[str],
) -> dict[str, Any]:
    return {
        "outcome_id": f"OUT-{contract_id}-{suffix}",
        "statement": statement,
        "completion_criteria": criteria,
        "concept_ids": [f"{contract_id}.{item}" for item in concept_suffixes],
        "accepted_block_types": block_types,
        "check_requirement": {
            "minimum_items": 1,
            "check_type": "short_scenario",
            "scoring_owner": "deterministic_assessment",
        },
    }


def _contract(
    knowledge_point_id: str,
    title: str,
    concepts: list[dict[str, str]],
    outcomes: list[dict[str, Any]],
    immutable_facts: list[str],
    excluded_scope: list[str],
    relationships: dict[str, list[dict[str, str]]],
    visual_kind: str = "concept_map",
) -> dict[str, Any]:
    return {
        "teaching_contract_id": f"TC-{knowledge_point_id}-V1",
        "contract_version": TEACHING_CONTRACT_VERSION,
        "knowledge_point_id": knowledge_point_id,
        "knowledge_point_name": title,
        "knowledge_point_version": "java-capability-pack-v1",
        "effective_at": "2026-08-23T00:00:00+08:00",
        "grade_scope": ["高职计算机信息技术专业群", "Java 应用开发"],
        "review": {
            "status": FORMAL_CONTRACT_REVIEW_STATUS,
            "reviewer": None,
            "verified": False,
            "note": "已完成结构与来源字段校验，专业内容仍需具名专家审核后标记 verified。",
        },
        "source_bundle": {
            "version": "java-core-source-bundle-v1",
            "sources": [
                {
                    "source": "《Java 核心技术·卷I》（原书第11版）",
                    "source_type": "textbook",
                    "document_id": "JAVA-CORE",
                    "locator": "对应知识点章节",
                },
                {
                    "source": "Oracle Java Documentation",
                    "source_type": "official_document",
                    "document_id": "ORACLE-JAVA-DOCS",
                    "locator": "由本次检索的可核验 URL 确定",
                },
            ],
        },
        "concepts": concepts,
        "relationships": relationships,
        "required_scope": [item["title"] for item in concepts],
        "excluded_scope": excluded_scope,
        "outcomes": outcomes,
        "immutable_facts": immutable_facts,
        "personalization_boundary": {
            "allowed": ["例子", "语气", "难度", "讲解速度", "结构图样式", "视频推荐顺序"],
            "forbidden": ["定义", "公式", "事实", "推导逻辑", "题目答案", "评分标准"],
        },
        "visual_spec": {
            "kind": visual_kind,
            "title": f"{title}知识结构图",
            "coverage_outcome_ids": [item["outcome_id"] for item in outcomes[:2]],
        },
    }


def _relation(knowledge_point_id: str, label: str) -> dict[str, str]:
    return {"knowledge_point_id": knowledge_point_id, "label": label}


FORMAL_TEACHING_CONTRACTS: dict[str, dict[str, Any]] = {
    "KN_JAVA_CLASS": _contract(
        "KN_JAVA_CLASS",
        "类的定义与对象创建",
        [
            _concept("KN_JAVA_CLASS", "class_structure", "类的结构", "class、字段、方法和构造器的职责。"),
            _concept("KN_JAVA_CLASS", "object_instance", "对象与引用", "对象是类的实例，引用变量保存对象引用。"),
            _concept("KN_JAVA_CLASS", "construction", "对象创建", "使用 new 调用构造器创建对象。"),
        ],
        [
            _outcome("KN_JAVA_CLASS", "01", "说出类、对象和引用变量的区别。", "能用自己的话区分类定义、对象实例与引用。", ["class_structure", "object_instance"], ["concept"]),
            _outcome("KN_JAVA_CLASS", "02", "完成一个包含字段、构造器和方法的最小类定义。", "能写出可编译的类定义并通过 new 创建对象。", ["class_structure", "construction"], ["steps", "example", "workplace"]),
            _outcome("KN_JAVA_CLASS", "03", "识别把类名当作对象使用等常见错误。", "能判断实例成员访问是否缺少对象引用。", ["object_instance"], ["warning", "pitfall", "check", "standard", "safety"]),
        ],
        ["类是对象的蓝图，对象是类的实例。", "new 调用构造器创建对象。"],
        ["继承、多态的实现细节", "集合框架 API 细节"],
        {"prerequisite": [], "parallel": [], "subsequent": [_relation("KN_JAVA_ENCAPSULATION", "封装建立在类与对象基础上")], "confusable": [], "extension": []},
    ),
    "KN_JAVA_ENCAPSULATION": _contract(
        "KN_JAVA_ENCAPSULATION",
        "封装与访问控制",
        [
            _concept("KN_JAVA_ENCAPSULATION", "access_modifier", "访问控制", "private 限制内部状态的直接访问。"),
            _concept("KN_JAVA_ENCAPSULATION", "controlled_api", "受控接口", "通过方法暴露受控读取或修改。"),
            _concept("KN_JAVA_ENCAPSULATION", "mutable_state", "可变状态保护", "避免暴露可直接修改的内部可变引用。"),
        ],
        [
            _outcome("KN_JAVA_ENCAPSULATION", "01", "说明封装为何要隐藏内部状态。", "能指出 private 与公开行为接口各自承担的职责。", ["access_modifier", "controlled_api"], ["concept"]),
            _outcome("KN_JAVA_ENCAPSULATION", "02", "为一个字段设计受控访问方法。", "能在 setter 中完成基本合法性校验，避免直接暴露字段。", ["controlled_api"], ["steps", "example", "workplace"]),
            _outcome("KN_JAVA_ENCAPSULATION", "03", "识别 getter 直接泄露可变内部引用的问题。", "能说明返回数组/集合内部引用会绕过封装。", ["mutable_state"], ["warning", "pitfall", "check", "standard", "safety"]),
        ],
        ["private 字段不能被类外代码直接访问。", "封装通过受控行为接口维护对象不变量。"],
        ["继承重写的完整规则", "多态分派机制"],
        {"prerequisite": [_relation("KN_JAVA_CLASS", "先能定义类与对象")], "parallel": [], "subsequent": [_relation("KN_JAVA_INHERITANCE", "子类继承前需要理解父类状态边界")], "confusable": [_relation("KN_JAVA_POLYMORPHISM", "封装隐藏状态，多态替换实现")], "extension": []},
        "comparison",
    ),
    "KN_JAVA_INHERITANCE": _contract(
        "KN_JAVA_INHERITANCE",
        "继承与方法重写",
        [
            _concept("KN_JAVA_INHERITANCE", "extends", "继承关系", "extends 表达子类对父类可复用成员的继承。"),
            _concept("KN_JAVA_INHERITANCE", "override", "方法重写", "子类以相同方法签名提供自己的实现。"),
            _concept("KN_JAVA_INHERITANCE", "super", "super 调用", "super 可访问父类构造器或被覆盖方法。"),
        ],
        [
            _outcome("KN_JAVA_INHERITANCE", "01", "区分继承与方法重写。", "能说明 extends 建立关系、重写改变子类行为。", ["extends", "override"], ["concept"]),
            _outcome("KN_JAVA_INHERITANCE", "02", "实现一个带 @Override 的子类方法。", "方法签名匹配父类，且能在需要时调用 super。", ["override", "super"], ["steps", "example", "workplace"]),
            _outcome("KN_JAVA_INHERITANCE", "03", "识别误以为重载就是重写的错误。", "能判断方法签名改变时不是重写。", ["override"], ["warning", "pitfall", "check", "standard", "safety"]),
        ],
        ["重写要求子类方法与父类方法具有兼容的方法签名。", "@Override 用于让编译器校验重写意图。"],
        ["接口多态的完整分派细节", "集合实现类的选择"],
        {"prerequisite": [_relation("KN_JAVA_ENCAPSULATION", "先理解父类状态应受控")], "parallel": [], "subsequent": [_relation("KN_JAVA_POLYMORPHISM", "多态以继承或接口关系为基础")], "confusable": [_relation("KN_JAVA_CLASS", "构造器不是普通可重写方法")], "extension": []},
        "flowchart",
    ),
    "KN_JAVA_POLYMORPHISM": _contract(
        "KN_JAVA_POLYMORPHISM",
        "多态与接口",
        [
            _concept("KN_JAVA_POLYMORPHISM", "interface_contract", "接口契约", "接口声明调用方依赖的行为。"),
            _concept("KN_JAVA_POLYMORPHISM", "polymorphic_reference", "多态引用", "父类型或接口引用可指向兼容实现对象。"),
            _concept("KN_JAVA_POLYMORPHISM", "dynamic_dispatch", "动态分派", "调用实际执行的实现取决于运行时对象。"),
        ],
        [
            _outcome("KN_JAVA_POLYMORPHISM", "01", "说明接口、实现类和多态引用的关系。", "能解释调用方为何依赖接口而非具体实现。", ["interface_contract", "polymorphic_reference"], ["concept"]),
            _outcome("KN_JAVA_POLYMORPHISM", "02", "使用接口类型变量调用不同实现。", "能替换实现类而不修改调用方的接口调用代码。", ["polymorphic_reference", "dynamic_dispatch"], ["steps", "example", "workplace"]),
            _outcome("KN_JAVA_POLYMORPHISM", "03", "区分多态与对象字段的静态访问。", "能识别方法调用与字段访问的差异。", ["dynamic_dispatch"], ["warning", "pitfall", "check", "standard", "safety"]),
        ],
        ["接口描述行为契约，实现类提供具体实现。", "实例方法调用可根据运行时对象选择实际实现。"],
        ["泛型协变与逆变", "反射机制"],
        {"prerequisite": [_relation("KN_JAVA_INHERITANCE", "先理解父子类型关系与重写")], "parallel": [], "subsequent": [], "confusable": [_relation("KN_JAVA_ENCAPSULATION", "封装关注状态边界，多态关注行为替换")], "extension": []},
        "state_transition",
    ),
    "KN_JAVA_COLLECTION": _contract(
        "KN_JAVA_COLLECTION",
        "集合与泛型",
        [
            _concept("KN_JAVA_COLLECTION", "list_interface", "List 接口", "List 表示有序、可重复的元素序列。"),
            _concept("KN_JAVA_COLLECTION", "generic_type", "泛型类型约束", "泛型在编译期限制集合元素类型。"),
            _concept("KN_JAVA_COLLECTION", "iteration", "集合遍历", "通过增强 for 或迭代器访问集合元素。"),
        ],
        [
            _outcome("KN_JAVA_COLLECTION", "01", "说出 List、实现类和泛型参数的作用。", "能解释 List 接口与 ArrayList 实现的关系。", ["list_interface", "generic_type"], ["concept"]),
            _outcome("KN_JAVA_COLLECTION", "02", "创建并遍历一个泛型集合。", "能添加指定类型元素并完成一次遍历。", ["generic_type", "iteration"], ["steps", "example", "workplace"]),
            _outcome("KN_JAVA_COLLECTION", "03", "识别原始类型集合带来的类型风险。", "能说明省略泛型会推迟类型错误发现。", ["generic_type"], ["warning", "pitfall", "check", "standard", "safety"]),
        ],
        ["泛型用于在编译期表达集合元素类型。", "List 是接口，ArrayList 是常见实现类。"],
        ["并发集合", "复杂集合性能比较"],
        {"prerequisite": [_relation("KN_JAVA_CLASS", "集合元素通常是对象")], "parallel": [_relation("KN_JAVA_EXCEPTION", "两者都可独立于面向对象进阶学习")], "subsequent": [_relation("KN_JAVA_IO", "文件读取结果常进入集合")], "confusable": [], "extension": []},
    ),
    "KN_JAVA_EXCEPTION": _contract(
        "KN_JAVA_EXCEPTION",
        "异常处理",
        [
            _concept("KN_JAVA_EXCEPTION", "exception_flow", "异常流程", "异常表示正常控制流之外的失败情况。"),
            _concept("KN_JAVA_EXCEPTION", "try_catch", "try-catch", "try 包裹可能失败的操作，catch 处理匹配异常。"),
            _concept("KN_JAVA_EXCEPTION", "checked_exception", "受检异常", "受检异常要求处理或声明。"),
        ],
        [
            _outcome("KN_JAVA_EXCEPTION", "01", "区分正常分支与异常处理。", "能说明不能用异常替代普通条件判断。", ["exception_flow"], ["concept"]),
            _outcome("KN_JAVA_EXCEPTION", "02", "为可能失败的操作编写 try-catch 或 throws。", "能覆盖异常路径并保留对用户可操作的提示。", ["try_catch", "checked_exception"], ["steps", "example", "workplace"]),
            _outcome("KN_JAVA_EXCEPTION", "03", "识别吞掉异常和泄露敏感细节的问题。", "能给出不暴露敏感数据的异常处理方式。", ["try_catch"], ["warning", "pitfall", "check", "standard", "safety"]),
        ],
        ["受检异常需要被捕获处理或在方法签名中声明。", "异常信息不应泄露密码、SQL 或个人敏感数据。"],
        ["自定义异常体系", "日志框架具体配置"],
        {"prerequisite": [_relation("KN_JAVA_CLASS", "异常处理代码写在类和方法中")], "parallel": [_relation("KN_JAVA_COLLECTION", "集合操作也可能需要异常边界")], "subsequent": [_relation("KN_JAVA_IO", "IO 操作常产生 IOException")], "confusable": [], "extension": []},
        "flowchart",
    ),
    "KN_JAVA_IO": _contract(
        "KN_JAVA_IO",
        "输入输出流",
        [
            _concept("KN_JAVA_IO", "stream_role", "流与资源", "输入流读取数据，输出流写入数据，资源需要关闭。"),
            _concept("KN_JAVA_IO", "buffered_reading", "缓冲读取", "BufferedReader 可按行读取字符数据。"),
            _concept("KN_JAVA_IO", "charset_resource", "字符集与资源管理", "显式字符集和 try-with-resources 避免乱码与泄漏。"),
        ],
        [
            _outcome("KN_JAVA_IO", "01", "说明读取、编码和资源关闭的基本职责。", "能解释为什么不应依赖平台默认字符集。", ["stream_role", "charset_resource"], ["concept"]),
            _outcome("KN_JAVA_IO", "02", "用 try-with-resources 完成一次按行读取。", "能显式指定 UTF-8 并处理 IOException。", ["buffered_reading", "charset_resource"], ["steps", "example", "workplace"]),
            _outcome("KN_JAVA_IO", "03", "识别资源泄漏、默认编码和路径穿越风险。", "能说明关闭资源与校验文件路径的原因。", ["stream_role", "charset_resource"], ["warning", "pitfall", "check", "standard", "safety"]),
        ],
        ["try-with-resources 会在语句结束时关闭实现 AutoCloseable 的资源。", "跨系统文本读写应显式指定字符集。"],
        ["NIO 异步通道", "复杂文件上传架构"],
        {"prerequisite": [_relation("KN_JAVA_EXCEPTION", "需要处理 IO 失败") , _relation("KN_JAVA_COLLECTION", "读取的多条记录常存入集合")], "parallel": [], "subsequent": [], "confusable": [], "extension": []},
        "flowchart",
    ),
}


def get_teaching_contract(knowledge_point_id: str) -> dict[str, Any] | None:
    contract = FORMAL_TEACHING_CONTRACTS.get(str(knowledge_point_id or "").strip())
    return deepcopy(contract) if contract else None


def _block_has_content(block: dict[str, Any]) -> bool:
    return bool(
        str(block.get("content") or block.get("markdown") or "").strip()
        or any(str(item or "").strip() for item in block.get("items", []) if isinstance(item, str))
    )


def annotate_lesson_with_contract(result: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Bind generated blocks and resources to contract outcomes deterministically."""
    annotated = dict(result)
    outcomes = [item for item in contract.get("outcomes", []) if isinstance(item, dict)]
    blocks: list[dict[str, Any]] = []
    for block in annotated.get("content_blocks", []):
        if not isinstance(block, dict):
            continue
        copied = dict(block)
        block_type = str(copied.get("type") or "").strip().lower()
        outcome_ids = [
            str(outcome["outcome_id"])
            for outcome in outcomes
            if block_type in set(outcome.get("accepted_block_types", [])) and _block_has_content(copied)
        ]
        concept_ids: list[str] = []
        for outcome in outcomes:
            if str(outcome.get("outcome_id") or "") in outcome_ids:
                concept_ids.extend(str(item) for item in outcome.get("concept_ids", []))
        copied["outcome_ids"] = list(dict.fromkeys(outcome_ids))
        copied["concept_ids"] = list(dict.fromkeys(concept_ids))
        copied["coverage_status"] = "covered" if outcome_ids else "context_only"
        blocks.append(copied)
    annotated["content_blocks"] = blocks
    annotated["teaching_contract"] = deepcopy(contract)
    annotated["teaching_contract_ref"] = {
        key: contract[key]
        for key in ("teaching_contract_id", "contract_version", "knowledge_point_version", "effective_at")
    }
    return annotated


def audit_lesson_contract(result: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Check outcome coverage and scope without treating an LLM as a scorer."""
    outcomes = [item for item in contract.get("outcomes", []) if isinstance(item, dict)]
    required_ids = [str(item.get("outcome_id") or "") for item in outcomes]
    covered_ids = {
        str(outcome_id)
        for block in result.get("content_blocks", [])
        if isinstance(block, dict)
        for outcome_id in block.get("outcome_ids", [])
        if str(outcome_id)
    }
    allowed_context_types = {"notice", "connection", "weakness_connection", "route_explanation"}
    unmapped_blocks = [
        str(block.get("block_id") or block.get("type") or "unknown")
        for block in result.get("content_blocks", [])
        if isinstance(block, dict)
        and str(block.get("type") or "").strip().lower() not in allowed_context_types
        and _block_has_content(block)
        and not block.get("outcome_ids")
    ]
    missing = [outcome_id for outcome_id in required_ids if outcome_id not in covered_ids]
    rendered_text = "\n".join(
        " ".join(
            [
                str(block.get("title") or ""),
                str(block.get("content") or block.get("markdown") or ""),
                " ".join(str(item or "") for item in block.get("items", []) if isinstance(item, str)),
            ]
        )
        for block in result.get("content_blocks", [])
        if isinstance(block, dict)
    )
    scope_violations = [
        item
        for item in contract.get("excluded_scope", [])
        if len(str(item).strip()) >= 3 and str(item).strip() in rendered_text
    ]
    return {
        "status": "passed" if not missing and not unmapped_blocks and not scope_violations else "rejected",
        "required_outcome_ids": required_ids,
        "covered_outcome_ids": sorted(covered_ids),
        "missing_outcome_ids": missing,
        "unmapped_blocks": unmapped_blocks,
        "scope_violations": scope_violations,
        "immutable_facts": list(contract.get("immutable_facts", [])),
        "excluded_scope": list(contract.get("excluded_scope", [])),
    }


def annotate_resources_with_contract(result: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Record what each resource is allowed to cover.

    A searched video has no transcript-level verification in this MVP, so it is
    deliberately kept out of outcome coverage even when it is relevant.
    """
    annotated = dict(result)
    covered_outcomes = sorted(
        {
            str(outcome_id)
            for block in annotated.get("content_blocks", [])
            if isinstance(block, dict)
            for outcome_id in block.get("outcome_ids", [])
            if str(outcome_id)
        }
    )
    resources: list[dict[str, Any]] = []
    for raw_resource in annotated.get("resources", []):
        if not isinstance(raw_resource, dict):
            continue
        resource = dict(raw_resource)
        resource_type = str(resource.get("type") or "").lower()
        if resource_type == "video":
            resource.setdefault("coverage_outcome_ids", [])
            resource.setdefault("coverage_status", "candidate_unverified")
            resource.setdefault("transcript_verified", False)
        elif resource_type == "document":
            resource.setdefault("coverage_outcome_ids", [])
            resource.setdefault("coverage_status", "source_reference_only")
        else:
            resource.setdefault("coverage_outcome_ids", covered_outcomes)
            resource.setdefault("coverage_status", "supplementary")
        resources.append(resource)
    resources.append(
        {
            "resource_id": f"TXT-{contract.get('knowledge_point_id')}-V1",
            "type": "text",
            "title": "本节目标讲解",
            "coverage_outcome_ids": covered_outcomes,
            "coverage_status": "covered_by_generated_blocks",
            "source": "TeachingContract v1 + 已核验讲解区块",
            "source_bundle_version": str(contract.get("source_bundle", {}).get("version") or ""),
        }
    )
    resources.append(build_contract_visual(contract))
    annotated["resources"] = resources
    return annotated


def build_contract_visual(contract: dict[str, Any]) -> dict[str, Any]:
    """Render an auditable SVG teaching diagram; it never generates factual artwork."""
    concepts = [item for item in contract.get("concepts", []) if isinstance(item, dict)]
    width = 760
    visual_spec = contract.get("visual_spec", {}) if isinstance(contract.get("visual_spec"), dict) else {}
    spec = visual_spec
    visual_kind = str(visual_spec.get("kind") or "concept_map").strip().lower()
    height = 140 + max(1, len(concepts)) * 92
    title = str(contract.get("knowledge_point_name") or "知识点")
    nodes: list[str] = []
    links: list[str] = []
    if visual_kind in {"flowchart", "state_transition"}:
        for index, concept in enumerate(concepts):
            y = 84 + index * 92
            label = escape(str(concept.get("title") or "原子知识点"))
            description = escape(str(concept.get("description") or ""))
            nodes.append(
                f'<rect x="185" y="{y}" width="390" height="56" rx="10" fill="#edf4ff" stroke="#3b82f6"/>'
                f'<text x="205" y="{y + 23}" font-size="16" font-weight="600" fill="#16325c">{label}</text>'
                f'<text x="205" y="{y + 43}" font-size="12" fill="#45617f">{description}</text>'
            )
            if index:
                links.append(f'<line x1="380" y1="{y - 28}" x2="380" y2="{y}" stroke="#7aa7df" stroke-width="2" marker-end="url(#arrow)"/>')
        height = 112 + max(1, len(concepts)) * 92
    elif visual_kind == "comparison":
        height = 174 + max(1, (len(concepts) + 1) // 2) * 100
        for index, concept in enumerate(concepts):
            column = index % 2
            row = index // 2
            x = 42 + column * 368
            y = 88 + row * 100
            label = escape(str(concept.get("title") or "原子知识点"))
            description = escape(str(concept.get("description") or ""))
            nodes.append(
                f'<rect x="{x}" y="{y}" width="330" height="64" rx="10" fill="#fff7e8" stroke="#d9a441"/>'
                f'<text x="{x + 18}" y="{y + 25}" font-size="15" font-weight="600" fill="#664810">{label}</text>'
                f'<text x="{x + 18}" y="{y + 46}" font-size="12" fill="#80652d">{description}</text>'
            )
    else:
        for index, concept in enumerate(concepts):
            y = 95 + index * 92
            label = escape(str(concept.get("title") or "原子知识点"))
            description = escape(str(concept.get("description") or ""))
            nodes.append(
                f'<rect x="300" y="{y}" width="390" height="56" rx="10" fill="#edf4ff" stroke="#3b82f6"/>'
                f'<text x="320" y="{y + 23}" font-size="16" font-weight="600" fill="#16325c">{label}</text>'
                f'<text x="320" y="{y + 43}" font-size="12" fill="#45617f">{description}</text>'
            )
            links.append(f'<line x1="210" y1="{height // 2}" x2="300" y2="{y + 28}" stroke="#7aa7df" stroke-width="2"/>')
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}知识结构图">'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="#7aa7df"/></marker></defs>'
        '<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<text x="32" y="42" font-size="22" font-weight="700" fill="#17335c">{escape(title)}：{escape({"flowchart": "学习流程", "state_transition": "状态变化", "comparison": "概念对比"}.get(visual_kind, "原子知识结构"))}</text>'
        + ("" if visual_kind in {"flowchart", "state_transition", "comparison"} else (
            f'<rect x="40" y="{height // 2 - 32}" width="170" height="64" rx="12" fill="#17335c"/>'
            f'<text x="62" y="{height // 2 + 6}" font-size="16" font-weight="600" fill="#ffffff">{escape(title)}</text>'
        ))
        + "".join(links)
        + "".join(nodes)
        + "</svg>"
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return {
        "resource_id": f"VIS-{contract.get('knowledge_point_id')}-V1",
        "type": "image",
        "renderer": "deterministic_svg",
        "ai_generated": False,
        "title": str(spec.get("title") or f"{title}知识结构图"),
        "visual_kind": visual_kind,
        "alt": f"{title}的原子知识点关系图",
        "coverage_outcome_ids": list(spec.get("coverage_outcome_ids", [])),
        "concept_ids": [str(item.get("concept_id") or "") for item in concepts],
        "source": "TeachingContract v1（确定性 SVG 渲染）",
        "source_bundle_version": str(contract.get("source_bundle", {}).get("version") or ""),
        "url": f"data:image/svg+xml;base64,{encoded}",
    }


def build_lesson_visual(result: dict[str, Any]) -> dict[str, Any] | None:
    """Render a deterministic overview from already generated lesson blocks."""
    if bool(result.get("knowledge_gap")) or str(result.get("status") or "ok") != "ok":
        return None
    blocks = [
        block
        for block in result.get("content_blocks", [])
        if isinstance(block, dict)
        and str(block.get("type") or "").strip().lower() not in {"notice", "connection", "route_explanation"}
        and str(block.get("title") or block.get("type") or "").strip()
        and _block_has_content(block)
    ]
    if not blocks:
        return None
    title = str(result.get("lesson_title") or result.get("knowledge_point_id") or "本章知识结构").strip()
    width = 860
    card_width = 235
    card_height = 72
    columns = 3
    rows = (len(blocks) + columns - 1) // columns
    height = 118 + rows * 108
    block_types = {str(block.get("type") or "").strip().lower() for block in blocks}
    visual_kind = "flowchart" if "steps" in block_types else "comparison" if block_types & {"warning", "pitfall"} else "concept_map"
    outcome_ids = sorted({
        str(outcome_id)
        for block in blocks
        for outcome_id in block.get("outcome_ids", [])
        if str(outcome_id)
    })

    def short(value: Any, limit: int) -> str:
        text = " ".join(str(value or "").split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}教学结构图">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="32" y="40" font-size="22" font-weight="700" fill="#17335c">{escape(title)}：教学结构图</text>',
        '<text x="32" y="66" font-size="12" fill="#60758f">图中内容来自本章已生成并通过基础结构校验的文字区块</text>',
    ]
    for index, block in enumerate(blocks):
        row, column = divmod(index, columns)
        x = 32 + column * 276
        y = 86 + row * 108
        block_title = short(block.get("title") or block.get("type") or "讲解内容", 24)
        block_text = block.get("content") or block.get("markdown") or ""
        if not block_text and isinstance(block.get("items"), list):
            block_text = "；".join(str(item) for item in block["items"][:2])
        block_type = short(block.get("type") or "content", 14)
        svg_parts.extend([
            f'<rect x="{x}" y="{y}" width="{card_width}" height="{card_height}" rx="12" fill="#edf4ff" stroke="#76a4d8"/>',
            f'<text x="{x + 14}" y="{y + 25}" font-size="15" font-weight="600" fill="#16325c">{escape(block_title)}</text>',
            f'<text x="{x + 14}" y="{y + 46}" font-size="11" fill="#45617f">{escape(short(block_text, 30))}</text>',
            f'<text x="{x + card_width - 14}" y="{y + 62}" text-anchor="end" font-size="10" fill="#6682a2">{escape(block_type)}</text>',
        ])
    svg_parts.append("</svg>")
    encoded = base64.b64encode("".join(svg_parts).encode("utf-8")).decode("ascii")
    return {
        "resource_id": f"VIS-{result.get('knowledge_point_id') or 'LESSON'}-{str(result.get('content_version') or 'CURRENT')}",
        "type": "image",
        "renderer": "deterministic_svg",
        "ai_generated": False,
        "title": f"{title}教学结构图",
        "alt": f"{title}的文字讲解结构图",
        "coverage_status": "derived_from_lesson_blocks",
        "visual_kind": visual_kind,
        "coverage_outcome_ids": outcome_ids,
        "coverage_block_ids": [str(block.get("block_id") or "") for block in blocks],
        "source": "已生成讲解区块（确定性 SVG 渲染）",
        "url": f"data:image/svg+xml;base64,{encoded}",
    }


def validate_teaching_contracts() -> None:
    for knowledge_point_id, contract in FORMAL_TEACHING_CONTRACTS.items():
        if contract.get("knowledge_point_id") != knowledge_point_id:
            raise ValueError(f"TeachingContract 知识点 ID 不一致：{knowledge_point_id}")
        concept_ids = {str(item.get("concept_id") or "") for item in contract.get("concepts", [])}
        outcome_ids: set[str] = set()
        for outcome in contract.get("outcomes", []):
            outcome_id = str(outcome.get("outcome_id") or "")
            if not outcome_id or outcome_id in outcome_ids:
                raise ValueError(f"TeachingContract 学习目标 ID 无效：{knowledge_point_id}")
            outcome_ids.add(outcome_id)
            if not outcome.get("completion_criteria") or not outcome.get("accepted_block_types"):
                raise ValueError(f"TeachingContract 学习目标缺少完成标准：{outcome_id}")
            if not set(outcome.get("concept_ids", [])) <= concept_ids:
                raise ValueError(f"TeachingContract 学习目标引用未知原子知识点：{outcome_id}")


validate_teaching_contracts()

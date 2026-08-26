"""目标图谱最小版（独立于知识库 seed）。

MVP 覆盖一个目标：完成 Java 面向对象成绩管理实训（7 个知识点）。
结构上按「目标 -> 知识点 -> 依赖」建模，便于后续扩展多目标。

数据契约（与 backend/goal_engine.py 对齐）：
- KNOWLEDGE_POINTS: 知识点元数据
- DEPENDENCIES: knowledge_point_id -> [前置知识点 id 列表]
- GOALS: 目标元数据，keywords 供口语化目标归一化匹配
"""

from typing import Any

GOAL_JAVA_001 = "GOAL-JAVA-001"
GOAL_JAVA_COMPETITION = "GOAL-JAVA-COMPETITION"
GOAL_JAVA_CERT = "GOAL-JAVA-CERT"
GOAL_JAVA_DAILY = "GOAL-JAVA-DAILY"

KNOWLEDGE_POINTS: dict[str, dict[str, Any]] = {
    "KN_JAVA_CLASS": {
        "knowledge_point_id": "KN_JAVA_CLASS",
        "knowledge_point_name": "类的定义与对象创建",
        "knowledge_type": "code",
        "description": "类与对象的区别、new 关键字创建对象、构造器与引用变量。",
    },
    "KN_JAVA_ENCAPSULATION": {
        "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
        "knowledge_point_name": "封装与访问控制",
        "knowledge_type": "conceptual",
        "description": "private 字段、getter/setter、对外只读接口，防止外部直接篡改内部状态。",
    },
    "KN_JAVA_INHERITANCE": {
        "knowledge_point_id": "KN_JAVA_INHERITANCE",
        "knowledge_point_name": "继承与方法重写",
        "knowledge_type": "code",
        "description": "extends 继承、方法重写与 @Override、子类复用与扩展父类行为。",
    },
    "KN_JAVA_POLYMORPHISM": {
        "knowledge_point_id": "KN_JAVA_POLYMORPHISM",
        "knowledge_point_name": "多态与接口",
        "knowledge_type": "conceptual",
        "description": "implements 接口、多态引用、接口解耦调用方与实现方。",
    },
    "KN_JAVA_COLLECTION": {
        "knowledge_point_id": "KN_JAVA_COLLECTION",
        "knowledge_point_name": "集合与泛型",
        "knowledge_type": "code",
        "description": "ArrayList/List 接口、add()/遍历、泛型约束元素类型。",
    },
    "KN_JAVA_EXCEPTION": {
        "knowledge_point_id": "KN_JAVA_EXCEPTION",
        "knowledge_point_name": "异常处理",
        "knowledge_type": "code",
        "description": "try-catch 捕获、受检异常、避免程序因单点错误中断。",
    },
    "KN_JAVA_IO": {
        "knowledge_point_id": "KN_JAVA_IO",
        "knowledge_point_name": "输入输出流",
        "knowledge_type": "code",
        "description": "BufferedReader + FileReader 按行读取文本，IOException 处理与资源关闭。",
    },
}

# 依赖关系（前置知识点必须出现在路径更早位置）
DEPENDENCIES: dict[str, list[str]] = {
    "KN_JAVA_ENCAPSULATION": ["KN_JAVA_CLASS"],
    "KN_JAVA_INHERITANCE": ["KN_JAVA_ENCAPSULATION"],
    "KN_JAVA_POLYMORPHISM": ["KN_JAVA_INHERITANCE"],
    "KN_JAVA_COLLECTION": ["KN_JAVA_CLASS"],
    "KN_JAVA_EXCEPTION": ["KN_JAVA_CLASS"],
    "KN_JAVA_IO": ["KN_JAVA_EXCEPTION", "KN_JAVA_COLLECTION"],
}

GOALS: dict[str, dict[str, Any]] = {
    GOAL_JAVA_001: {
        "goal_id": GOAL_JAVA_001,
        "goal_type": "course",
        "goal_name": "完成 Java 面向对象成绩管理实训",
        "goal_description": "掌握 Java 面向对象核心语法，能够独立完成成绩管理实训任务。",
        "keywords": [
            "java",
            "java 面向对象",
            "面向对象",
            "java 成绩",
            "成绩管理",
            "面向对象实训",
            "java 实训",
            "java 对象",
            "对象",
            "类",
        ],
        # 推荐学习顺序（与依赖关系一致）
        "knowledge_points": [
            "KN_JAVA_CLASS",
            "KN_JAVA_ENCAPSULATION",
            "KN_JAVA_INHERITANCE",
            "KN_JAVA_POLYMORPHISM",
            "KN_JAVA_COLLECTION",
            "KN_JAVA_EXCEPTION",
            "KN_JAVA_IO",
        ],
    },
    GOAL_JAVA_COMPETITION: {
        "goal_id": GOAL_JAVA_COMPETITION,
        "goal_type": "competition",
        "goal_name": "备战世界职业院校技能大赛",
        "goal_description": "对标 Java 程序设计赛项，覆盖面向对象核心知识并侧重综合应用与竞赛题型。",
        "keywords": [
            "大赛",
            "技能大赛",
            "世界职业院校技能大赛",
            "java 赛项",
            "竞赛",
            "备赛",
            "competition",
        ],
        "knowledge_points": [
            "KN_JAVA_CLASS",
            "KN_JAVA_ENCAPSULATION",
            "KN_JAVA_INHERITANCE",
            "KN_JAVA_POLYMORPHISM",
            "KN_JAVA_COLLECTION",
            "KN_JAVA_EXCEPTION",
            "KN_JAVA_IO",
        ],
    },
    GOAL_JAVA_CERT: {
        "goal_id": GOAL_JAVA_CERT,
        "goal_type": "certification",
        "goal_name": "1+X Java 应用开发认证",
        "goal_description": "对照 1+X 证书考核范围，知识体系全覆盖，注重规范与基础准确性。",
        "keywords": [
            "1+x",
            "认证",
            "1+X 认证",
            "java 应用开发认证",
            "考证",
            "证书",
            "certification",
        ],
        "knowledge_points": [
            "KN_JAVA_CLASS",
            "KN_JAVA_ENCAPSULATION",
            "KN_JAVA_INHERITANCE",
            "KN_JAVA_POLYMORPHISM",
            "KN_JAVA_COLLECTION",
            "KN_JAVA_EXCEPTION",
            "KN_JAVA_IO",
        ],
    },
    GOAL_JAVA_DAILY: {
        "goal_id": GOAL_JAVA_DAILY,
        "goal_type": "daily",
        "goal_name": "日常技能提升",
        "goal_description": "面向岗位能力图谱查漏补缺，优先补齐薄弱知识点。",
        "keywords": [
            "日常",
            "提升",
            "查漏补缺",
            "补弱",
            "daily",
            "日常技能",
        ],
        "knowledge_points": [
            "KN_JAVA_CLASS",
            "KN_JAVA_ENCAPSULATION",
            "KN_JAVA_INHERITANCE",
            "KN_JAVA_POLYMORPHISM",
            "KN_JAVA_COLLECTION",
            "KN_JAVA_EXCEPTION",
            "KN_JAVA_IO",
        ],
    },
}

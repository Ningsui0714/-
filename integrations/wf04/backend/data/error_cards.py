"""错误卡配置（P1-3 归因查表化）：knowledge_point_id -> 错误定义列表。

业务逻辑不再硬编码知识点分支：
- domain.create_practice 的变式练习模板由 variant_practice_for() 生成；
- server._finalize_diagnosis 的薄弱点归因由 default_error_card_for() 补充
  错误类型 / 误解标签 / 根因。
新知识点只需在此加配置，不动逻辑。
"""

from typing import Any

ERROR_CARDS: dict[str, list[dict[str, Any]]] = {
    "KN_JAVA_CLASS": [
        {
            "error_id": "CLASS_NEW_SYNTAX",
            "knowledge_point_id": "KN_JAVA_CLASS",
            "error_type": "syntax",
            "misconception_tag": "new 创建对象语法混淆",
            "root_cause": "对象必须用 new 调用构造器创建，不能把类名当函数直接调用",
            "diagnosis": "创建对象的语句不符合 Java 语法",
            "severity": "low",
            "confidence": 0.9,
        },
        {
            "error_id": "CLASS_NULL_REFERENCE",
            "knowledge_point_id": "KN_JAVA_CLASS",
            "error_type": "concept",
            "misconception_tag": "未初始化引用即使用",
            "root_cause": "引用变量未指向任何对象就访问成员，触发空指针",
            "diagnosis": "使用未初始化的引用访问对象成员",
            "severity": "medium",
            "confidence": 0.9,
        },
    ],
    "KN_JAVA_ENCAPSULATION": [
        {
            "error_id": "ENCAP_EXPOSED_ARRAY_REF",
            "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
            "error_type": "encapsulation_leak",
            "misconception_tag": "直接暴露内部引用",
            "root_cause": "getter 直接返回内部数组引用，外部可绕过校验改写数据",
            "diagnosis": "应返回副本或只读视图，setter 校验 null 与越界",
            "severity": "medium",
            "confidence": 1.0,
            "variant_practice": {
                "title": "封装变式题：getter/setter",
                "prompt": "为 Student 类补全 getter/setter，确保外部无法直接修改成绩数组（要求：不暴露内部数组引用）。",
                "schema": {"type": "text", "label": "代码", "placeholder": "粘贴补全后的代码"},
                "expected_answer": "提供 getScores() 返回副本或只读视图，setScores() 做 null/越界校验",
            },
        },
        {
            "error_id": "ENCAP_PRIVATE_ACCESS",
            "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
            "error_type": "access_control",
            "misconception_tag": "private 字段外部直接访问",
            "root_cause": "外部类直接读写私有字段，破坏了封装边界",
            "diagnosis": "私有字段应通过公开的 getter/setter 访问",
            "severity": "low",
            "confidence": 0.9,
        },
    ],
    "KN_JAVA_INHERITANCE": [
        {
            "error_id": "INHERIT_OVERRIDE_SUPER",
            "knowledge_point_id": "KN_JAVA_INHERITANCE",
            "error_type": "override",
            "misconception_tag": "重写后无法复用父类逻辑",
            "root_cause": "重写方法后未用 super 调用父类被覆盖的版本，统计口径丢失",
            "diagnosis": "super 关键字调用父类被重写的方法以复用父类逻辑",
            "severity": "medium",
            "confidence": 1.0,
            "variant_practice": {
                "title": "继承变式题：重写 averageScore",
                "prompt": "子类 StudentWithBonus 继承 Student 并重写 averageScore()。要求说明：如何复用父类统计逻辑并加上加分，且不修改父类。",
                "schema": {"type": "text", "label": "说明", "placeholder": "输入实现思路"},
                "expected_answer": "super.averageScore() 复用统计口径，再在子类中叠加 bonus 处理",
            },
        },
        {
            "error_id": "INHERIT_EXTENDS_IMPL",
            "knowledge_point_id": "KN_JAVA_INHERITANCE",
            "error_type": "syntax",
            "misconception_tag": "extends / implements 混用",
            "root_cause": "类继承用 extends，接口实现用 implements，二者混用导致编译错误",
            "diagnosis": "继承父类使用 extends 关键字",
            "severity": "low",
            "confidence": 0.9,
        },
    ],
    "KN_JAVA_POLYMORPHISM": [
        {
            "error_id": "POLY_UPCAST_CALL",
            "knowledge_point_id": "KN_JAVA_POLYMORPHISM",
            "error_type": "concept",
            "misconception_tag": "父类引用无法调用子类新增方法",
            "root_cause": "父类引用变量只保证能调用父类声明的方法，调用子类特有方法需要向下转型",
            "diagnosis": "多态引用调用的是被子类重写的方法，运行期动态绑定",
            "severity": "medium",
            "confidence": 0.9,
        },
        {
            "error_id": "POLY_INTERFACE_CONTRACT",
            "knowledge_point_id": "KN_JAVA_POLYMORPHISM",
            "error_type": "design",
            "misconception_tag": "接口只约定行为契约",
            "root_cause": "接口的价值是解耦调用方与实现方，而非提供方法体",
            "diagnosis": "接口定义行为契约，不同实现可替换",
            "severity": "medium",
            "confidence": 0.9,
        },
    ],
    "KN_JAVA_COLLECTION": [
        {
            "error_id": "COLL_REMOVE_IN_LOOP",
            "knowledge_point_id": "KN_JAVA_COLLECTION",
            "error_type": "algorithm",
            "misconception_tag": "遍历中删除元素方式错误",
            "root_cause": "for 循环按索引 remove 会越界或漏删元素",
            "diagnosis": "遍历删除应使用 Iterator.remove 或 removeIf",
            "severity": "medium",
            "confidence": 0.9,
        },
        {
            "error_id": "COLL_TYPE_UNSAFE",
            "knowledge_point_id": "KN_JAVA_COLLECTION",
            "error_type": "safety",
            "misconception_tag": "集合未使用泛型",
            "root_cause": "无泛型约束时取出的元素需要强转，类型不安全",
            "diagnosis": "声明集合时使用泛型约束元素类型",
            "severity": "low",
            "confidence": 0.9,
        },
    ],
    "KN_JAVA_EXCEPTION": [
        {
            "error_id": "EXC_UNCAUGHT_RUNTIME",
            "knowledge_point_id": "KN_JAVA_EXCEPTION",
            "error_type": "safety",
            "misconception_tag": "运行时异常未处理导致程序中断",
            "root_cause": "空指针/除零等运行时异常未捕获，程序在关键路径中断",
            "diagnosis": "对可能抛运行时异常的代码做防御性判空与 try-catch",
            "severity": "high",
            "confidence": 0.9,
        },
        {
            "error_id": "EXC_RESOURCE_LEAK",
            "knowledge_point_id": "KN_JAVA_EXCEPTION",
            "error_type": "resource",
            "misconception_tag": "资源未自动关闭",
            "root_cause": "finally 手动 close 在异常分支容易遗漏",
            "diagnosis": "使用 try-with-resources 自动关闭资源",
            "severity": "medium",
            "confidence": 0.9,
        },
    ],
    "KN_JAVA_IO": [
        {
            "error_id": "IO_STREAM_BASE",
            "knowledge_point_id": "KN_JAVA_IO",
            "error_type": "concept",
            "misconception_tag": "字节流与字符流基类混淆",
            "root_cause": "字节流基类是 InputStream/OutputStream，字符流是 Reader/Writer",
            "diagnosis": "按数据类型选择字节流或字符流",
            "severity": "low",
            "confidence": 0.9,
        },
        {
            "error_id": "IO_READLINE",
            "knowledge_point_id": "KN_JAVA_IO",
            "error_type": "algorithm",
            "misconception_tag": "按行读取方式低效",
            "root_cause": "用 FileInputStream 逐字节读取不如 BufferedReader.readLine() 便捷高效",
            "diagnosis": "按行读取文本使用 BufferedReader.readLine()",
            "severity": "low",
            "confidence": 0.9,
        },
    ],
}

DEFAULT_VARIANT_PRACTICE: dict[str, Any] = {
    "title": "同知识点变式题",
    "prompt": "请用自己的话说明当前知识点的核心规则，并给出一个应用例子。",
    "schema": {"type": "text", "label": "你的答案", "placeholder": "输入答案"},
    "expected_answer": "说明核心规则并给出例子",
}


def error_cards_for(knowledge_id: str) -> list[dict[str, Any]]:
    """返回该知识点的全部错误卡；无配置时返回空列表。"""
    return ERROR_CARDS.get(knowledge_id, [])


def default_error_card_for(knowledge_id: str) -> dict[str, Any]:
    """返回该知识点首张错误卡（归因默认值）；无配置时返回空 dict。"""
    cards = ERROR_CARDS.get(knowledge_id)
    return cards[0] if cards else {}


def variant_practice_for(knowledge_id: str) -> dict[str, Any]:
    """返回该知识点首个带变式练习模板的错误卡；无配置时返回通用模板。"""
    for card in ERROR_CARDS.get(knowledge_id, []):
        template = card.get("variant_practice")
        if template:
            return template
    return DEFAULT_VARIANT_PRACTICE

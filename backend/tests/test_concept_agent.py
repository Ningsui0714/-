from app.services.concept_agent import ConceptAgent


def test_legacy_code_question_names_are_compatibility_aliases():
    assert ConceptAgent._canonical_question_type("wwpd") == "code_output"
    assert ConceptAgent._canonical_question_type("WWPP") == "code_output"
    assert ConceptAgent._canonical_question_type("code_output") == "code_output"
    assert ConceptAgent._canonical_question_type("invented_type") is None


def test_verified_code_answer_is_unique_and_not_forced_to_first_option():
    options, answer_indexes = ConceptAgent._verified_code_options(
        "下面程序输出什么？",
        "42",
        ["41", "42", "43", "44", "42"],
    )

    assert options.count("42") == 1
    assert len(options) == 4
    assert options[answer_indexes[0]] == "42"

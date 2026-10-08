from app.study.assignments import build_question_assignments, list_assessments_for_subject


def test_list_chemistry_assessments():
    ids = list_assessments_for_subject("data", "chemistry")
    assert "C-JUN25-8464C1H-02_3" in ids


def test_list_biology_assessments():
    ids = list_assessments_for_subject("data", "biology")
    assert "B-JUN24-84612H-05_6" in ids


def test_build_assignments_for_subject():
    questions = build_question_assignments("data", "chemistry")
    assert len(questions) >= 1
    assert questions[0]["assessment_id"] == "C-JUN25-8464C1H-02_3"

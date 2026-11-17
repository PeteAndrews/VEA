"""Fixed study questionnaires, validation, and versioned scoring.

Item wording for SUS, NASA-TLX and UEQ follows the published instruments
named in docs/study-questionnaires-plan.md. Scoring runs at export time
and does not replace stored answers.
"""

from __future__ import annotations

from typing import Any

FORM_VERSION = 1

PREFER_NOT = "prefer_not"
TEXT_LIMIT = 500
EXPLANATION_LIMIT = 2000

POST_CONDITION_KEYS = ("nasa_tlx_raw", "sus", "ueq")

_LIKERT7 = [
    {"id": "1", "label": "1 Strongly disagree"},
    {"id": "2", "label": "2 Disagree"},
    {"id": "3", "label": "3 Somewhat disagree"},
    {"id": "4", "label": "4 Neither agree nor disagree"},
    {"id": "5", "label": "5 Somewhat agree"},
    {"id": "6", "label": "6 Agree"},
    {"id": "7", "label": "7 Strongly agree"},
    {"id": PREFER_NOT, "label": "Prefer not to say"},
]

_SUS_OPTIONS = [
    {"id": "1", "label": "Strongly disagree"},
    {"id": "2", "label": "Disagree"},
    {"id": "3", "label": "Neither agree nor disagree"},
    {"id": "4", "label": "Agree"},
    {"id": "5", "label": "Strongly agree"},
]


def _single(item_id: str, prompt: str, options: list[tuple[str, str]], **extra: Any) -> dict[str, Any]:
    item = {
        "id": item_id,
        "kind": "single",
        "prompt": prompt,
        "options": [{"id": option_id, "label": label} for option_id, label in options],
    }
    item.update(extra)
    return item


def background_definition() -> dict[str, Any]:
    return {
        "key": "background",
        "version": FORM_VERSION,
        "scope": "study",
        "title": "Background questionnaire",
        "introduction": (
            "These questions help us understand participants' backgrounds and previous experience. "
            "Please do not include your name, school or other identifying details in written answers. "
            "You may choose \"Prefer not to say\" for any question."
        ),
        "items": [
            _single(
                "age",
                "What is your age group?",
                [
                    ("18_24", "18–24"),
                    ("25_34", "25–34"),
                    ("35_44", "35–44"),
                    ("45_54", "45–54"),
                    ("55_64", "55–64"),
                    ("65_over", "65 or over"),
                    (PREFER_NOT, "Prefer not to say"),
                ],
            ),
            _single(
                "gender",
                "How do you describe your gender?",
                [
                    ("woman", "Woman"),
                    ("man", "Man"),
                    ("non_binary", "Non-binary"),
                    ("self_describe", "Prefer to self-describe"),
                    (PREFER_NOT, "Prefer not to say"),
                ],
                text_option="self_describe",
                text_field="gender_text",
                text_label="Self-description (optional)",
            ),
            {
                "id": "roles",
                "kind": "multi",
                "prompt": "Which associate role or roles do you currently hold?",
                "exclusive": ["not_applicable", PREFER_NOT],
                "text_option": "other",
                "text_field": "roles_text",
                "text_label": "Other role (optional)",
                "options": [
                    {"id": "associate_chief", "label": "Associate Chief Examiner"},
                    {"id": "associate_lead", "label": "Associate Lead Examiner"},
                    {"id": "associate_assistant_lead", "label": "Associate Assistant Lead Examiner"},
                    {"id": "associate_examiner", "label": "Associate Examiner"},
                    {"id": "associate_general_marker", "label": "Associate General Marker"},
                    {"id": "associate_reserve", "label": "Associate Reserve"},
                    {"id": "chair", "label": "Chair of Examiners"},
                    {"id": "other", "label": "Other"},
                    {"id": "not_applicable", "label": "Not applicable"},
                    {"id": PREFER_NOT, "label": "Prefer not to say"},
                ],
            },
            _single(
                "teaching_years",
                "How many years of teaching experience do you have in total? Count completed years, including previous roles.",
                [
                    ("none", "None"),
                    ("lt_1", "Less than 1 year"),
                    ("1_2", "1–2 years"),
                    ("3_5", "3–5 years"),
                    ("6_10", "6–10 years"),
                    ("11_15", "11–15 years"),
                    ("16_plus", "16 years or more"),
                    (PREFER_NOT, "Prefer not to say"),
                ],
            ),
            _single(
                "marking_years_count",
                "In how many separate calendar years have you marked external examinations for an awarding organisation? Count each year once, even if you marked more than one series. Exclude classroom marking and internal mock examinations.",
                [
                    ("none", "None"),
                    ("1_2", "1–2 years"),
                    ("3_5", "3–5 years"),
                    ("6_10", "6–10 years"),
                    ("11_15", "11–15 years"),
                    ("16_plus", "16 years or more"),
                    (PREFER_NOT, "Prefer not to say"),
                ],
            ),
            {
                "id": "marking_years",
                "kind": "multi",
                "prompt": "In which of the following years have you marked external examinations?",
                "exclusive": ["not_applicable", PREFER_NOT],
                "options": [
                    {"id": "2026", "label": "2026"},
                    {"id": "2025", "label": "2025"},
                    {"id": "2024", "label": "2024"},
                    {"id": "2023", "label": "2023"},
                    {"id": "2022", "label": "2022"},
                    {"id": "2021", "label": "2021"},
                    {"id": "2020", "label": "2020"},
                    {"id": "2019_or_earlier", "label": "2019 or earlier"},
                    {"id": "not_applicable", "label": "Not applicable — I have not marked external examinations"},
                    {"id": PREFER_NOT, "label": "Prefer not to say"},
                ],
            },
            _single(
                "ai_frequency",
                "During the past three months, how often have you used conversational AI tools such as ChatGPT, Microsoft Copilot or Google Gemini? Include use for work or personal purposes. Select the closest description.",
                [
                    ("never", "Never"),
                    ("lt_monthly", "Less than once a month"),
                    ("few_monthly", "A few times a month"),
                    ("weekly", "About once a week"),
                    ("several_weekly", "Several times a week"),
                    ("daily", "Daily or almost daily"),
                    (PREFER_NOT, "Prefer not to say"),
                ],
            ),
            {
                "id": "ai_statements",
                "kind": "note",
                "prompt": (
                    "For the following statements, AI-assisted marking means a system that provides suggestions "
                    "or explanations while the human examiner retains the final marking decision."
                ),
            },
            {
                "id": "willing",
                "kind": "single",
                "prompt": "I would be willing to use AI suggestions when making marking decisions.",
                "options": _LIKERT7,
            },
            {
                "id": "expect_quality",
                "kind": "single",
                "prompt": "I expect AI assistance could improve the quality of my marking decisions.",
                "options": _LIKERT7,
            },
        ],
    }


_TLX_SCALES = [
    (
        "mental",
        "Mental demand",
        "How much mental and perceptual activity was required (for example thinking, deciding, calculating, remembering, looking, searching)? Was the task easy or demanding, simple or complex, exacting or forgiving?",
        "Low",
        "High",
    ),
    (
        "physical",
        "Physical demand",
        "How much physical activity was required (for example pushing, pulling, turning, controlling, activating)? Was the task easy or demanding, slow or brisk, slack or strenuous, restful or laborious?",
        "Low",
        "High",
    ),
    (
        "temporal",
        "Temporal demand",
        "How much time pressure did you feel due to the rate or pace at which the tasks occurred? Was the pace slow and leisurely or rapid and frantic?",
        "Low",
        "High",
    ),
    (
        "performance",
        "Performance",
        "How successful do you think you were in accomplishing the goals of the task? How satisfied were you with your performance in accomplishing these goals?",
        "Good",
        "Poor",
    ),
    (
        "effort",
        "Effort",
        "How hard did you have to work (mentally and physically) to accomplish your level of performance?",
        "Low",
        "High",
    ),
    (
        "frustration",
        "Frustration",
        "How insecure, discouraged, irritated, stressed and annoyed versus secure, gratified, content, relaxed and complacent did you feel during the task?",
        "Low",
        "High",
    ),
]


def nasa_tlx_definition() -> dict[str, Any]:
    return {
        "key": "nasa_tlx_raw",
        "version": FORM_VERSION,
        "title": "NASA Task Load Index",
        "introduction": (
            "These ratings concern the experimental marking tasks you have just completed, not the practice walkthrough. "
            "Each scale runs from 0 to 100 in steps of 5. Select a mark on every scale. "
            "On Performance, the high end of the scale represents poorer performance."
        ),
        "source": "https://ntrs.nasa.gov/api/citations/20000021488/downloads/20000021488.pdf",
        "items": [
            {
                "id": scale_id,
                "kind": "ticks",
                "prompt": title,
                "definition": definition,
                "min_label": low,
                "max_label": high,
                "min": 0,
                "max": 100,
                "step": 5,
            }
            for scale_id, title, definition, low, high in _TLX_SCALES
        ],
    }


_SUS_ITEMS = [
    "I think that I would like to use this system frequently.",
    "I found the system unnecessarily complex.",
    "I thought the system was easy to use.",
    "I think that I would need the support of a technical person to be able to use this system.",
    "I found the various functions in this system were well integrated.",
    "I thought there was too much inconsistency in this system.",
    "I would imagine that most people would learn to use this system very quickly.",
    "I found the system very cumbersome to use.",
    "I felt very confident using the system.",
    "I needed to learn a lot of things before I could get going with this system.",
]


def sus_definition(*, interface_label: str) -> dict[str, Any]:
    return {
        "key": "sus",
        "version": FORM_VERSION,
        "title": "System Usability Scale",
        "introduction": (
            f"Please rate the interface you have just used (Interface {interface_label}). "
            "In the statements below, \"this system\" means that interface. "
            "Do not spend a long time on each statement."
        ),
        "source": "Brooke, J. (1996). SUS: a quick and dirty usability scale.",
        "items": [
            {
                "id": str(index),
                "kind": "single",
                "prompt": text,
                "options": _SUS_OPTIONS,
            }
            for index, text in enumerate(_SUS_ITEMS, start=1)
        ],
    }


# Official UEQ English pairs, questionnaire order. positive is the pole that scores +3 at that end.
# Scales follow the UEQ handbook item mapping.
_UEQ_ITEMS = [
    ("1", "annoying", "enjoyable", "right", "attractiveness"),
    ("2", "not understandable", "understandable", "right", "perspicuity"),
    ("3", "creative", "dull", "left", "novelty"),
    ("4", "easy to learn", "difficult to learn", "left", "perspicuity"),
    ("5", "valuable", "inferior", "left", "stimulation"),
    ("6", "boring", "exciting", "right", "stimulation"),
    ("7", "not interesting", "interesting", "right", "stimulation"),
    ("8", "unpredictable", "predictable", "right", "dependability"),
    ("9", "fast", "slow", "left", "efficiency"),
    ("10", "inventive", "conventional", "left", "novelty"),
    ("11", "obstructive", "supportive", "right", "dependability"),
    ("12", "good", "bad", "left", "attractiveness"),
    ("13", "complicated", "easy", "right", "perspicuity"),
    ("14", "unlikable", "pleasing", "right", "attractiveness"),
    ("15", "usual", "leading edge", "right", "novelty"),
    ("16", "unpleasant", "pleasant", "right", "attractiveness"),
    ("17", "secure", "not secure", "left", "dependability"),
    ("18", "motivating", "demotivating", "left", "stimulation"),
    ("19", "meets expectations", "does not meet expectations", "left", "dependability"),
    ("20", "inefficient", "efficient", "right", "efficiency"),
    ("21", "clear", "confusing", "left", "perspicuity"),
    ("22", "impractical", "practical", "right", "efficiency"),
    ("23", "organized", "cluttered", "left", "efficiency"),
    ("24", "attractive", "unattractive", "left", "attractiveness"),
    ("25", "friendly", "unfriendly", "left", "attractiveness"),
    ("26", "conservative", "innovative", "right", "novelty"),
]


def ueq_definition(*, interface_label: str) -> dict[str, Any]:
    return {
        "key": "ueq",
        "version": FORM_VERSION,
        "title": "User Experience Questionnaire",
        "introduction": (
            f"Considering your experience completing the marking tasks using Interface {interface_label}, "
            "please evaluate that interface using the word pairs below. "
            "The circles between each pair are gradations between the two words. "
            "Please decide spontaneously. There are no right or wrong answers."
        ),
        "source": "https://www.ueq-online.org/Material/Handbook.pdf",
        "items": [
            {
                "id": item_id,
                "kind": "pair",
                "left": left,
                "right": right,
                "positions": 7,
            }
            for item_id, left, right, _positive, _scale in _UEQ_ITEMS
        ],
    }


def preference_definition(*, label_a: str, label_b: str) -> dict[str, Any]:
    return {
        "key": "preference",
        "version": FORM_VERSION,
        "scope": "study",
        "title": "Interface preference",
        "introduction": "Having used both interfaces, which would you prefer to use for similar marking tasks?",
        "reminders": [
            {"id": "A", "condition": label_a, "text": f"Interface A was the {label_a} marking interface."},
            {"id": "B", "condition": label_b, "text": f"Interface B was the {label_b} marking interface."},
        ],
        "items": [
            _single(
                "choice",
                "Having used both interfaces, which would you prefer to use for similar marking tasks?",
                [("A", "Interface A"), ("B", "Interface B"), ("none", "No preference")],
            ),
            {
                "id": "explanation",
                "kind": "text",
                "prompt": "Please briefly explain your preference (or why you have no preference).",
                "optional": True,
            },
        ],
    }


def public_definition(form: dict[str, Any]) -> dict[str, Any]:
    """Drop scoring-only fields before sending a form to the participant."""
    return form


def _option_ids(item: dict[str, Any]) -> set[str]:
    return {option["id"] for option in item.get("options") or []}


def _check_text(value: Any, limit: int, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return f"{field} must be text"
    if len(value) > limit:
        return f"{field} is too long"
    return None


def validate_answers(form: dict[str, Any], answers: Any, *, complete: bool) -> list[str]:
    if not isinstance(answers, dict):
        return ["Answers must be an object"]
    errors: list[str] = []
    for item in form["items"]:
        if item["kind"] == "note":
            continue
        item_id = item["id"]
        value = answers.get(item_id)
        if item["kind"] == "text":
            problem = _check_text(value, EXPLANATION_LIMIT, item_id)
            if problem:
                errors.append(problem)
            if complete and not item.get("optional") and not (isinstance(value, str) and value.strip()):
                errors.append(f"{item_id} is required")
            continue
        if item["kind"] == "single":
            if value in (None, ""):
                if complete:
                    errors.append(f"{item_id} is required")
                continue
            if value not in _option_ids(item):
                errors.append(f"{item_id} is not a valid choice")
            text_field = item.get("text_field")
            if text_field:
                problem = _check_text(answers.get(text_field), TEXT_LIMIT, text_field)
                if problem:
                    errors.append(problem)
            continue
        if item["kind"] == "multi":
            selected = value or []
            if selected in ("", None):
                selected = []
            if not isinstance(selected, list) or not all(isinstance(entry, str) for entry in selected):
                errors.append(f"{item_id} must be a list")
                continue
            unknown = [entry for entry in selected if entry not in _option_ids(item)]
            if unknown:
                errors.append(f"{item_id} has an invalid choice")
            exclusive = set(item.get("exclusive") or [])
            if exclusive.intersection(selected) and len(selected) > 1:
                errors.append(f"{item_id} cannot combine that choice with others")
            if complete and not selected:
                errors.append(f"{item_id} is required")
            text_field = item.get("text_field")
            if text_field:
                problem = _check_text(answers.get(text_field), TEXT_LIMIT, text_field)
                if problem:
                    errors.append(problem)
            continue
        if item["kind"] == "ticks":
            if value in (None, ""):
                if complete:
                    errors.append(f"{item_id} is required")
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                errors.append(f"{item_id} must be a whole number")
                continue
            if value < item["min"] or value > item["max"] or (value - item["min"]) % item["step"]:
                errors.append(f"{item_id} must be between {item['min']} and {item['max']} in steps of {item['step']}")
            continue
        if item["kind"] == "pair":
            if value in (None, ""):
                if complete:
                    errors.append(f"{item_id} is required")
                continue
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= item["positions"]:
                errors.append(f"{item_id} must be a position from 1 to {item['positions']}")
    if form["key"] == "background" and complete:
        count = answers.get("marking_years_count")
        years = answers.get("marking_years") or []
        named_years = [year for year in years if year not in {"not_applicable", PREFER_NOT}]
        if count == "none" and named_years:
            errors.append("Marking years contradict the answer that you have not marked external examinations")
    return errors


def score_answers(key: str, answers: dict[str, Any]) -> dict[str, Any] | None:
    if key == "nasa_tlx_raw":
        values = [int(answers[scale_id]) for scale_id, *_rest in _TLX_SCALES]
        return {"unweighted_mean": sum(values) / len(values), "n": len(values)}
    if key == "sus":
        total = 0
        for index in range(1, 11):
            value = int(answers[str(index)])
            total += (value - 1) if index % 2 else (5 - value)
        return {"score": total * 2.5}
    if key == "ueq":
        grouped: dict[str, list[float]] = {}
        for item_id, _left, _right, positive, scale in _UEQ_ITEMS:
            raw = int(answers[item_id])
            coded = (raw - 4) if positive == "right" else (4 - raw)
            grouped.setdefault(scale, []).append(coded)
        return {scale: sum(values) / len(values) for scale, values in grouped.items()}
    return None

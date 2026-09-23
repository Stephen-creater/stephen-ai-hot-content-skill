"""Test helper: a final-review card that answers every yes/no question the passing way."""
import json
from pathlib import Path

QUESTIONS = json.loads((Path(__file__).resolve().parents[1] / "resources/review_questions.json").read_text(encoding="utf-8"))["questions"]


def passing_answers(**overrides) -> dict:
    answers = {
        q["id"]: {"answer": "no" if q["veto_if"] == "yes" else "yes", "note": "正文给出了具体证据，足够支撑这一题的回答", "quote": ""}
        for q in QUESTIONS
    }
    for key, value in overrides.items():
        answers[key] = {**answers[key], **(value if isinstance(value, dict) else {"answer": value})}
    return answers

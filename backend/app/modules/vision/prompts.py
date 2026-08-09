"""Prompts instruct vision models to report visible facts without diagnosis."""

import json


SCHEMA = {
    "image_type": "medical_report|medical_image|document|photo|unknown",
    "summary": "visible-fact summary",
    "visible_text": ["exact visible text"],
    "measurements": [{"name": "", "value": "", "unit": None, "reference_range": None, "flag": None}],
    "objects": [],
    "spatial_notes": [],
    "uncertain_content": [],
    "safety_flags": [],
}


def build_vision_prompt(user_question: str, focus_instruction: str | None) -> str:
    focus = focus_instruction or "先整体观察图片，记录与用户问题相关的可见事实"
    return (
        "你是医疗知识检索系统的图片观察器，只记录图片中可见事实。禁止诊断、处方、治疗建议，"
        "禁止补写图片外信息。模糊或不确定内容必须写入 uncertain_content。"
        f"\n用户问题：{user_question[:2000]}\n本次观察目标：{focus}"
        "\n只输出一个 JSON 对象，不要代码围栏。结构："
        + json.dumps(SCHEMA, ensure_ascii=False)
    )

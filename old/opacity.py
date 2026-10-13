import re
from dataclasses import dataclass, asdict

import ollama
import yaml
import json

@dataclass
class VisualState:
    video: bool
    text_density: float
    visual_density: float
    contrast: float

@dataclass
class ParsedVisualState:
    state: VisualState | None
    raw: str

    def to_dict(self) -> dict:
        return asdict(self)

def decide_opacity(state: VisualState) -> float:
    if state.video:
        return 1.0

    if state.text_density > 0.7:
        return 1.0

    if state.visual_density > 0.8:
        return 0.95

    return 0.85

def analyze_window_img(img_byte: bytes) -> ParsedVisualState:
    response = ollama.chat(
        model="qwen3.5:0.8b",
        stream=False,
        think=False,
        messages=[{
            "role": "user",
            "content": """
            Analyze this window screenshot.

            Return YAML with:
            ```yaml
            video: boolean
            text_density: number from 0 to 1
            visual_density: number from 0 to 1
            contrast: number from 0 to 1
            ```
            """,
            "images": [img_byte],
        }],
    )

    data = response["message"]["content"]

    return _parse_visual_state(data)


def _parse_yaml(raw: str) -> dict:
    match = re.search(
        r"```(?:yaml)?\s*\n(.*?)```",
        raw,
        re.DOTALL | re.IGNORECASE,
    )

    content = match.group(1) if match else raw
    return yaml.safe_load(content)

def _parse_visual_state(raw: str) -> ParsedVisualState:
    data = None

    try:
        data = _parse_yaml(raw)
    except yaml.YAMLError:
        print("[WARN] invalid yaml input passed to visual state parser")
    
    return ParsedVisualState(data, raw)

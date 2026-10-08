from dataclasses import dataclass
import ollama
import json

@dataclass
class VisualState:
    video: bool
    text_density: float
    visual_density: float
    contrast: float

def decide_opacity(state: VisualState) -> float:
    if state.video:
        return 1.0

    if state.text_density > 0.7:
        return 1.0

    if state.visual_density > 0.8:
        return 0.95

    return 0.85

def analyze_window_img(img_byte: bytes) -> str:
    response = ollama.chat(
        model="qwen3.5:0.8b",
        stream=False,
        think=False,
        messages=[{
            "role": "user",
            "content": """
            Analyze this window screenshot.

            Return JSON with:
            - video: boolean
            - text_density: number from 0 to 1
            - visual_density: number from 0 to 1
            - contrast: number from 0 to 1
            """,
            "images": [img_byte],
        }],
    )

    data = response["message"]["content"]

    return data
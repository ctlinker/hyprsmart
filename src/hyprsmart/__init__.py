from io import BytesIO

from PIL import Image

from .window import capture_window, get_hyprland_windows
import ollama

def main() -> None:
    wins = get_hyprland_windows()
    images = [
        capture_window(win) for win in wins
    ]

    for img_byte in images:

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

    print(response["message"]["content"])        

    


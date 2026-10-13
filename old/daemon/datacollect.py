from pathlib import Path
import json
import time
import uuid

DATASET = Path("dataset")

def save_sample(win, img, state):
    sample = DATASET / str(uuid.uuid4())
    sample.mkdir(parents=True)

    (sample / "image.png").write_bytes(img)

    metadata = {
        "timestamp": time.time(),
        "window": {
            "address": win.address,
            "title": win.title,
            "x": win.x,
            "y": win.y,
            "width": win.width,
            "height": win.height,
        },
        "prediction": state.to_dict()
    }

    (sample / "metadata.json").write_text(
        json.dumps(metadata, indent=2)
    )
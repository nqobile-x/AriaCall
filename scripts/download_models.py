"""Download Kokoro and Whisper models at build time."""
import os
import urllib.request
from pathlib import Path

MODELS_DIR = Path("voice/models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

KOKORO = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin":  "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}

for name, url in KOKORO.items():
    dest = MODELS_DIR / name
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"✓ {name} already present ({dest.stat().st_size // 1_000_000}MB)")
        continue
    print(f"↓ Downloading {name} …")
    urllib.request.urlretrieve(url, dest)
    print(f"✓ {name} saved ({dest.stat().st_size // 1_000_000}MB)")

print("Models ready.")

"""Download only the pinned CPU inference artifacts, with a local hash manifest."""

import hashlib
import json
from pathlib import Path
import urllib.request

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL_FILES = ("onnx/model.onnx", "sentence_bert_config.json", "config.json",
               "tokenizer.json", "tokenizer_config.json", "1_Pooling/config.json")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_model(cache_dir, offline=False):
    directory = Path(cache_dir) / f"minilm-onnx-{MODEL_REVISION}"
    manifest_path = directory / "artifact_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("revision") != MODEL_REVISION or set(manifest["files"]) != set(MODEL_FILES):
            raise ValueError("Model artifact manifest does not match the pinned revision")
        for filename in MODEL_FILES:
            file = directory / filename
            if not file.is_file() or sha256(file) != manifest["files"][filename]:
                raise ValueError(f"Model artifact missing or changed: {filename}. Remove its cache and download again.")
        return directory, manifest
    if offline:
        raise OSError("Pinned model is not downloaded. Run python -m freight_assistant.download_model once online.")
    directory.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for filename in MODEL_FILES:
        destination = directory / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{MODEL_NAME}/resolve/{MODEL_REVISION}/{filename}"
        print(f"Preparing local model: {filename}", flush=True)
        # Replace atomically so interrupted downloads cannot become model files.
        partial = destination.with_suffix(destination.suffix + ".partial")
        request = urllib.request.Request(url, headers={"User-Agent": "freight-cost-assistant/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
        partial.replace(destination)
        hashes[filename] = sha256(destination)
    manifest = {"model": MODEL_NAME, "revision": MODEL_REVISION, "files": hashes}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return directory, manifest


if __name__ == "__main__":
    directory, manifest = ensure_model(Path(__file__).resolve().parents[1] / ".cache/models")
    print(f"Model ready: {directory}")

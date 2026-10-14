"""Compare ONNX output with an independent Sentence Transformers reference."""

import json

from .pipeline import ROOT
from .reporting import file_hash, write_json
from .retrieval import NoteRetriever
from .validation import load_notes


def main():
    import numpy as np

    provenance = json.loads((ROOT / "evaluation/reference_embeddings.json").read_text())
    reference_path = ROOT / "evaluation/reference_note_embeddings.npy"
    if file_hash(reference_path) != provenance["reference_sha256"]:
        raise ValueError("Independent reference embeddings changed")
    if file_hash(ROOT / "data/context_notes.csv") != provenance["notes_csv_sha256"]:
        raise ValueError("Context notes differ from the reference corpus")
    notes = load_notes(ROOT / "data/context_notes.csv")
    retriever = NoteRetriever(notes, "semantic", ROOT / ".cache/models", offline=True)
    # Recompute rather than checking the persisted ONNX document-vector cache.
    actual = retriever._encode(retriever.texts)
    expected = np.load(reference_path, allow_pickle=False)
    close = np.allclose(actual, expected, atol=1e-5, rtol=1e-5)
    report = {"passed": bool(close), "reference": provenance,
              "shape": list(actual.shape), "maximum_absolute_difference": float(np.max(np.abs(actual - expected))),
              "minimum_reference_cosine": float(np.min(np.sum(actual * expected, axis=1))),
              "atol": 1e-5, "rtol": 1e-5,
              "method": "Recomputed ONNX token embeddings with masked mean pooling and normalization versus independently generated Sentence Transformers vectors for all ten notes."}
    write_json(ROOT / "results/encoder_verification.json", report)
    print(json.dumps(report, indent=2))
    return 0 if close else 1


if __name__ == "__main__":
    raise SystemExit(main())

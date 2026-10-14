"""Local dense semantic retrieval and an explicitly labeled offline lexical mode."""

import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path

from .download_model import MODEL_NAME, MODEL_REVISION, ensure_model


def query_for(row):
    return (f"Why did freight shipping costs increase on {row['route']} during the week of "
            f"{row['week_of']}? Evidence of fuel price rises, toll increases, flooding, "
            "detours or festival surcharges that increased transportation costs.")


class NoteRetriever:
    def __init__(self, notes, mode="semantic", cache_dir=None, offline=False):
        if mode not in {"semantic", "lexical"}:
            raise ValueError("Retriever must be semantic or lexical")
        self.notes, self.mode = notes, mode
        self.stats = {"mode": mode, "documents": len(notes), "queries": 0,
                      "embedding_model": MODEL_NAME if mode == "semantic" else None,
                      "model_revision": MODEL_REVISION if mode == "semantic" else None,
                      "embedding_input_tokens": 0, "embedding_inference_batches": 0,
                      "document_embedding_cache_hit": False}
        self.texts = [f"{n.applies_to}. {n.published.isoformat()}. {n.text}" for n in notes]
        if mode == "semantic":
            cache_dir = Path(cache_dir or Path.cwd() / ".cache/models").resolve()
            # Keep downloads and metadata within this project, including when
            # running in a restricted desktop workspace.
            os.environ.setdefault("HF_HOME", str(cache_dir / "hub_home"))
            os.environ.setdefault("HF_XET_CACHE", str(cache_dir / "xet"))
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer

            model_directory, manifest = ensure_model(cache_dir, offline)
            self.stats["artifact_sha256"] = manifest["files"]
            self.stats["backend"] = "onnx-fp32-cpu"
            options = ort.SessionOptions()
            options.intra_op_num_threads = options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            self.session = ort.InferenceSession(str(model_directory / "onnx/model.onnx"), options,
                                                providers=["CPUExecutionProvider"])
            self.input_names = {item.name for item in self.session.get_inputs()}
            self.tokenizer = Tokenizer.from_file(str(model_directory / "tokenizer.json"))
            encoder_config = json.loads((model_directory / "sentence_bert_config.json").read_text())
            self.tokenizer.enable_truncation(max_length=encoder_config["max_seq_length"])
            self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
            pooling = json.loads((model_directory / "1_Pooling/config.json").read_text())
            if not pooling.get("pooling_mode_mean_tokens") or pooling.get("pooling_mode_cls_token"):
                raise ValueError("Pinned model no longer matches the expected mean-pooling configuration")
            cache_path = Path(cache_dir)
            cache_path.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(("onnx-fp32-v1\n" + MODEL_REVISION + "\n" + "\n".join(self.texts)).encode()).hexdigest()
            vector_file = cache_path / f"notes-{digest}.npy"
            if vector_file.exists():
                self.vectors = np.load(vector_file, allow_pickle=False)
                self.stats["document_embedding_cache_hit"] = True
            else:
                self.vectors = self._encode(self.texts)
                np.save(vector_file, self.vectors, allow_pickle=False)
            self.stats["embedding_dimension"] = int(self.vectors.shape[1])
        else:
            self.documents = [Counter(self._tokens(text)) for text in self.texts]
            self.idf = {word: math.log((1 + len(notes)) /
                        (1 + sum(word in document for document in self.documents))) + 1
                        for word in set().union(*self.documents)}
            self.vectors = [self._vector(document) for document in self.documents]

    @staticmethod
    def _tokens(text):
        return re.findall(r"[a-z0-9]+", text.lower())

    def _vector(self, counts):
        weighted = {word: count * self.idf.get(word, 0) for word, count in counts.items()}
        norm = math.sqrt(sum(v * v for v in weighted.values())) or 1
        return {word: value / norm for word, value in weighted.items()}

    def _encode(self, texts):
        import numpy as np

        embeddings = []
        for offset in range(0, len(texts), 32):
            encoded = self.tokenizer.encode_batch(texts[offset:offset + 32])
            inputs = {
                "input_ids": np.array([item.ids for item in encoded], dtype=np.int64),
                "attention_mask": np.array([item.attention_mask for item in encoded], dtype=np.int64),
                "token_type_ids": np.array([item.type_ids for item in encoded], dtype=np.int64),
            }
            self.stats["embedding_input_tokens"] += int(inputs["attention_mask"].sum())
            self.stats["embedding_inference_batches"] += 1
            outputs = self.session.run(None, {name: value for name, value in inputs.items()
                                             if name in self.input_names})
            hidden = outputs[0]
            if hidden.ndim != 3 or hidden.shape[-1] != 384:
                raise ValueError("Unexpected pinned encoder output shape")
            # Masked mean pooling and L2 normalization follow the model card.
            mask = inputs["attention_mask"][..., None].astype(np.float32)
            pooled = (hidden * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
            pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9, None)
            embeddings.append(pooled)
        return np.concatenate(embeddings)

    def rank_many(self, queries):
        if not queries:
            return []
        self.stats["queries"] += len(queries)
        if self.mode == "semantic":
            scores = self._encode(queries) @ self.vectors.T
        else:
            vectors = [self._vector(Counter(self._tokens(query))) for query in queries]
            scores = [[sum(weight * document.get(word, 0) for word, weight in query.items())
                       for document in self.vectors] for query in vectors]
        return [sorted([{"note_id": note.note_id, "score": round(float(score), 8)}
                        for note, score in zip(self.notes, row)],
                       key=lambda hit: (-hit["score"], hit["note_id"])) for row in scores]

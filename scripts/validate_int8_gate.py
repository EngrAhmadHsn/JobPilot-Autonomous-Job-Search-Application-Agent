"""FU-7 Spec 7 validation gate: int8 vs fp32 EmbeddingGemma-2 quality comparison.

One-time (re-runnable) live gate that must pass BEFORE the corpus is migrated
to the quantized model: register both ONNX variants with fastembed, embed a
deterministic sample of the persisted corpus under both, and compare top-10
rankings per query.

Gate (04-pipeline-and-api.md, Spec 7): >=90% of queries with >=9/10 top-10
overlap between int8 and fp32, else the migration identity falls back to
``google/embeddinggemma-2@fp32``.

The script also settles FU-7's open items empirically (do-not-assume list):

1. ``sentence_embedding`` is mean-pooled and L2-normalized inside the graph
   (norm ~= 1.0, identical outputs for identical inputs).
2. The text graph runs with only ``input_ids`` + ``attention_mask``.
3. fastembed tolerates the repo's missing ``special_tokens_map.json``.
4. Over-cap input is truncated (not an error); the effective token cap comes
   from ``tokenizer_config.json``.

Usage:
    python scripts/validate_int8_gate.py                 # full gate (both variants)
    python scripts/validate_int8_gate.py --docs 200 --queries 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType

HF_REPO = "onnx-community/embeddinggemma-2-ONNX"
INT8_NAME = f"{HF_REPO}:int8"
FP32_NAME = f"{HF_REPO}:fp32"
DIM = 768


def register_variants() -> None:
    """Register both quantization variants (Spec 3 recipe, verbatim flags)."""
    common = {
        "pooling": PoolingType.DISABLED,  # graph mean-pools internally
        "normalization": False,  # graph L2-normalizes internally
        "sources": ModelSource(hf=HF_REPO),
        "dim": DIM,
        "output_name": "sentence_embedding",  # validated at load time by fastembed
    }
    TextEmbedding.add_custom_model(
        model=INT8_NAME,
        model_file="onnx/model_quantized.onnx",
        additional_files=["onnx/model_quantized.onnx_data"],
        **common,
    )
    TextEmbedding.add_custom_model(
        model=FP32_NAME,
        model_file="onnx/model.onnx",
        additional_files=["onnx/model.onnx_data"],
        **common,
    )


def load_corpus(limit: int) -> tuple[list[str], list[str]]:
    """Deterministic sample of persisted listings: embedded docs + held-out queries.

    Documents are the first ``limit`` rows by id; queries are title+company
    strings from rows *after* the sample (cross-document retrieval, not
    self-retrieval).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.config.settings import get_settings
    from src.db.jobs import JobDB

    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    with sessionmaker(bind=engine)() as session:
        rows = session.query(JobDB).order_by(JobDB.id).limit(limit + 40).all()
    engine.dispose()
    if len(rows) < 30:
        raise SystemExit(f"Corpus too small for the gate: {len(rows)} rows")

    def document_text(row) -> str:
        parts = []
        if row.required_skills:
            parts.append(f"Required skills: {row.required_skills}.")
        if row.description:
            parts.append(row.description[:6000])
        return f"title: {row.title} | text: {' '.join(parts)}"

    def query_text(row) -> str:
        return f"task: search result | query: {row.title} {row.company}".strip()

    docs = [document_text(row) for row in rows[:limit]]
    queries = [query_text(row) for row in rows[limit : limit + 20]]
    return docs, queries


def embed(model: TextEmbedding, texts: list[str]) -> np.ndarray:
    # 256 (fastembed default) OOMs outright; 16 OOMs the int8 MatMulNBits
    # buffers; 8 is the largest verified-safe batch (see FastembedEmbedding).
    vectors = model.embed(texts, batch_size=8)
    return np.asarray(list(vectors), dtype=np.float32)


def open_item_checks(model: TextEmbedding, tokenizer_config_path: Path) -> dict:
    """Empirically settle open items 1, 2, and 4 (item 3 is proven by loading)."""
    checks: dict = {}
    vectors = embed(model, ["senior python engineer at a product company"])
    checks["norm"] = float(np.linalg.norm(vectors[0]))
    checks["deterministic"] = bool(
        np.allclose(vectors[0], embed(model, ["senior python engineer at a product company"])[0])
    )
    # Open item 2: fastembed feeds the session only input_ids + attention_mask;
    # a successful embed with extra graph inputs left unspecified proves the
    # text-only path. Input names recorded for the doc.
    session = model.model.model  # onnxruntime InferenceSession under the shim
    checks["input_names"] = [inp.name for inp in session.get_inputs()]
    checks["output_names"] = [out.name for out in session.get_outputs()]
    # Open item 4: far over-cap input must truncate, not error.
    long_text = "python backend " * 4000  # ~56k chars
    long_vector = embed(model, [long_text])[0]
    checks["long_input_dim"] = int(long_vector.shape[0])
    checks["long_input_finite"] = bool(np.isfinite(long_vector).all())
    if tokenizer_config_path.exists():
        config = json.loads(tokenizer_config_path.read_text(encoding="utf-8"))
        checks["model_max_length"] = config.get("model_max_length")
    return checks


def top10_sets(doc_vectors: np.ndarray, query_vectors: np.ndarray, k: int = 10) -> list[set[int]]:
    """Top-k document indices per query by cosine similarity (vectors are unit)."""
    sims = query_vectors @ doc_vectors.T
    return [set(np.argsort(-row)[:k].tolist()) for row in sims]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", type=int, default=200)
    parser.add_argument("--queries", type=int, default=20)
    parser.add_argument(
        "--cache-dir", default=str(REPO_ROOT / "data" / "fastembed"), help="fastembed model cache"
    )
    parser.add_argument(
        "--variant",
        choices=("both", "fp32", "int8"),
        default="both",
        help="Embed only one variant this process (the other comes from its "
        "vector cache at comparison time). One variant per process: the "
        "onnxruntime arena retains memory, and two variants in one process "
        "OOM mid-batch (live-verified 'bad allocation').",
    )
    args = parser.parse_args()

    register_variants()
    from src.llm.embeddings import _TextOnlySession, ensure_tokenizer_context

    ensure_tokenizer_context(args.cache_dir)  # sentinel model_max_length shim (FU-7 finding)
    docs, queries = load_corpus(args.docs)
    print(f"Corpus sample: {len(docs)} documents, {len(queries)} queries", flush=True)

    variants = {"fp32": FP32_NAME, "int8": INT8_NAME}
    order = list(variants) if args.variant == "both" else [args.variant]

    results: dict = {}
    for variant_key in order:
        name = variants[variant_key]
        # Vector cache: embedding 200 fp32 docs takes ~13 min of CPU; a re-run
        # (e.g. after fixing the other variant's download) must not redo it.
        cache_file = Path(args.cache_dir) / f"gate-vectors-{variant_key}.npz"
        if cache_file.exists():
            blob = np.load(cache_file)
            results[name] = {"docs": blob["docs"], "queries": blob["queries"]}
            print(f"{name}: loaded {len(blob['docs'])} doc vectors from {cache_file}", flush=True)
            continue
        # Sequential construct→embed→free: keeping both ONNX sessions resident
        # exhausts RAM mid-batch (live-verified "bad allocation"), and the
        # weights are cached anyway so construction is instant.
        started = time.monotonic()
        model = TextEmbedding(
            model_name=name, cache_dir=args.cache_dir, providers=["CPUExecutionProvider"]
        )
        model.model.model = _TextOnlySession(model.model.model)  # fused graph needs zeros
        print(f"{name}: loaded in {time.monotonic() - started:.1f}s", flush=True)

        if name == INT8_NAME:
            candidates = sorted(
                Path(args.cache_dir).glob("models--*/snapshots/*/tokenizer_config.json")
            )
            tokenizer_config = candidates[0] if candidates else Path("<not-downloaded>")
            results["open_items"] = open_item_checks(model, tokenizer_config)
            print("open items:", json.dumps(results["open_items"], indent=2), flush=True)

        t0 = time.monotonic()
        results[name] = {
            "docs": embed(model, docs),
            "queries": embed(model, queries),
        }
        print(
            f"{name}: embedded {len(docs)} docs + {len(queries)} queries "
            f"in {time.monotonic() - t0:.1f}s",
            flush=True,
        )
        np.savez(
            cache_file,
            docs=results[name]["docs"],
            queries=results[name]["queries"],
        )

    if not {FP32_NAME, INT8_NAME} <= results.keys():
        print("One variant's vectors are still missing; re-run with the other --variant.")
        return 0

    fp32, int8 = results[FP32_NAME], results[INT8_NAME]
    fp32_top = top10_sets(fp32["docs"], fp32["queries"])
    int8_top = top10_sets(int8["docs"], int8["queries"])

    overlaps = [len(a & b) for a, b in zip(fp32_top, int8_top)]
    passing = sum(1 for overlap in overlaps if overlap >= 9)
    gate_ratio = passing / len(overlaps)

    print("\nPer-query top-10 overlap (int8 vs fp32):")
    for index, overlap in enumerate(overlaps):
        print(f"  query {index:02d}: {overlap}/10")
    verdict = "PASS" if gate_ratio >= 0.9 else "FAIL"
    print(
        f"\nGate: {passing}/{len(overlaps)} queries with >=9/10 overlap "
        f"({gate_ratio:.0%}) -> {verdict}"
    )

    # Open item 5 evidence: record the downloaded blob ids for the doc.
    metadata = (
        Path(args.cache_dir) / f"models--{HF_REPO.replace('/', '--')}" / "files_metadata.json"
    )
    if not metadata.exists():
        candidates = list(Path(args.cache_dir).rglob("files_metadata.json"))
        metadata = candidates[0] if candidates else metadata
    if metadata.exists():
        blob = json.loads(metadata.read_text(encoding="utf-8"))
        print(f"\nfiles_metadata.json ({metadata}):")
        print(json.dumps(blob, indent=2)[:2000])

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

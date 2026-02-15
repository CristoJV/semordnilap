import argparse
import logging
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from semordnilap.load import load_embeddings, load_lexicon

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("transformers").setLevel(logging.WARNING)

# MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
MODEL_NAME = "intfloat/multilingual-e5-base"


def build_faiss_index(embeddings: np.ndarray) -> faiss.Index:
    faiss.normalize_L2(embeddings)

    d = embeddings.shape[1]
    index: faiss.Index = faiss.IndexFlatIP(d)
    index.add(embeddings)

    print(f"Vectores indexados: {index.ntotal}")

    return index


def save_faiss_index(index: faiss.Index, path: Path) -> None:
    faiss.write_index(index, str(path))


def load_faiss_index(path: Path) -> faiss.Index:
    return faiss.read_index(str(path))


def query_index(
    query: str, index: faiss.Index, model: SentenceTransformer, k: int
):
    query_vec = model.encode(
        [f"query: {query}"], convert_to_numpy=True
    ).astype("float32")
    faiss.normalize_L2(query_vec)
    scores, indices = index.search(query_vec, k)
    return scores[0], indices[0]


def build_argparser():
    parser = argparse.ArgumentParser("Embed lexicon")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # BUILD
    build_parser = subparsers.add_parser("build")

    build_parser.add_argument(
        "-s",
        "--src",
        help="Lexicon filepath",
        required=True,
    )
    build_parser.add_argument(
        "-o",
        "--out",
        help="Output dirpath. Saves it ({lexicon}.npz and {lexicon_index})",
        required=True,
    )
    build_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in {output_dir}",
    )
    build_parser.add_argument(
        "--build-index", action="store_true", help="Build and save FAISS index"
    )

    # QUERY
    query_parser = subparsers.add_parser("query")

    query_parser.add_argument("-q", "--query", required=True)
    query_parser.add_argument("-e", "--embeddings", required=True)
    query_parser.add_argument("-i", "--index", required=True)
    query_parser.add_argument("-k", type=int, default=20)

    return parser


def build(args: argparse.Namespace) -> None:
    source_path = Path(args.src)
    output_dir = Path(args.out)

    output_dir.mkdir(parents=True, exist_ok=True)
    base_name: str = source_path.stem

    embeddings_path = output_dir / f"{base_name}.npz"
    index_path = output_dir / f"{base_name}.faiss"

    if embeddings_path.exists() and not args.force:
        logger.info(f"Using existing embeddings from {embeddings_path}")
        _, embeddings = load_embeddings(embeddings_path)
        embeddings = embeddings.astype("float32")
    else:
        if embeddings_path.exists():
            logger.warning(f"Overwriting embeddings at {embeddings_path}")
        lexicon = load_lexicon(source_path)
        logger.info(f"Loaded {len(lexicon)} words")

        model = SentenceTransformer(MODEL_NAME)
        embeddings: np.ndarray = model.encode(
            [f"passage: {w}" for w in lexicon],
            convert_to_numpy=True,
            show_progress_bar=True,
        ).astype("float32")
        np.savez(
            embeddings_path, words=np.array(lexicon), embeddings=embeddings
        )
        logger.info(f"Saved embeddings to: {embeddings_path}")

    if args.build_index:
        if index_path.exists() and not args.force:
            logger.info(f"Using exising index at {index_path}")
        else:
            if index_path.exists():
                logger.warning(f"Overwriting index at {index_path}")
            index = build_faiss_index(embeddings)
            save_faiss_index(index, index_path)
            logger.info(f"Saved FAISS index at {index_path}")


def query(args: argparse.Namespace) -> None:
    model = SentenceTransformer(MODEL_NAME)
    embeddings_path = Path(args.embeddings)
    words, embeddings = load_embeddings(embeddings_path)
    index_path = Path(args.index)

    logger.info(f"Loading FAISS index from {index_path}")
    index = load_faiss_index(index_path)
    scores, indices = query_index(args.query, index, model, args.k)

    logger.info("Most similar words:")
    for score, idx in zip(scores, indices):
        print(words[idx], float(score))


def main():
    parser = build_argparser()
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    if args.command == "query":
        query(args)


if __name__ == "__main__":
    main()

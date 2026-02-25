from semordnilap.embed.engine import E5Engine, EmbeddingEngine, QwenEngine


def load_engine(engine_name: str) -> EmbeddingEngine:
    engine_name = engine_name.lower()

    if engine_name == "e5":
        return E5Engine("intfloat/multilingual-e5-base")

    if engine_name == "qwen":
        return QwenEngine("Qwen/Qwen3-Embedding-0.6B")

    raise ValueError(f"Unknown engine: {engine_name}")

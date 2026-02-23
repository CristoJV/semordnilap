import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from torch import Tensor
from tqdm import tqdm
from transformers import AutoModel, AutoTokenizer


# INFO:
# Embedding Engines never normalizes output embeddings
class EmbeddingEngine:
    def encode_passages(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError

    def encode_query(self, text: str) -> np.ndarray:
        raise NotImplementedError


class E5Engine(EmbeddingEngine):
    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)

    def encode_passages(self, texts):
        return self.model.encode(
            [f"passage: {t}" for t in texts], convert_to_numpy=True
        )

    def encode_query(self, text: str):
        return self.model.encode([f"query: {text}"], convert_to_numpy=True)


def last_token_pool(
    last_hidden_states: Tensor, attention_mask: Tensor
) -> Tensor:
    left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
    if left_padding:
        return last_hidden_states[:, -1]
    else:
        sequence_lengths = attention_mask.sum(dim=1) - 1
        batch_size = last_hidden_states.shape[0]
        return last_hidden_states[
            torch.arange(batch_size, device=last_hidden_states.device),
            sequence_lengths,
        ]


class QwenEngine(EmbeddingEngine):
    def __init__(self, model_name):
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name, padding_side="left"
        )
        self.model = AutoModel.from_pretrained(model_name)
        if torch.cuda.is_available():
            self.model = self.model.to("cuda")
            print("Using GPU")
        else:
            print("NOT using GPU")

        self.model.eval()
        self.task_description = "Retrieve semantically similar words"

    def _format_query(self, text: str) -> str:
        return f"Instruct: {self.task_description}\nQuery: {text}"

    def encode_passages(self, texts, batch_size=1024):
        all_embeddings = []

        for i in tqdm(
            range(0, len(texts), batch_size),
            desc="Encoding passages",
            unit="batch",
        ):
            batch = texts[i : i + batch_size]

            inputs = self.tokenizer(
                batch, padding=True, truncation=True, return_tensors="pt"
            ).to(self.model.device)

            with torch.no_grad():
                outputs = self.model(**inputs)

            embeddings = last_token_pool(
                outputs.last_hidden_state, inputs["attention_mask"]
            )

            all_embeddings.append(embeddings.cpu())

        return torch.cat(all_embeddings).numpy()

    def encode_query(self, text):
        formatted = self._format_query(text)
        return self.encode_passages([formatted])

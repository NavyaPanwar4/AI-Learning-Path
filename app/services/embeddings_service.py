from typing import List, Optional, Tuple

from sentence_transformers import SentenceTransformer, util

from app.utils.config import settings
from app.utils.logger import logger


class EmbeddingsService:
    """Wraps a sentence-transformer model for semantic skill matching —
    used instead of plain string similarity so that phrasing differences
    and abbreviations (e.g. "JS" vs "JavaScript", "ML" vs "Machine
    Learning") still match correctly, which fuzzy string matching alone
    cannot do since it has no notion of meaning.

    The model is loaded lazily and cached — loading it is the slow part
    (a few seconds), so every service that needs matching should share
    this one instance rather than constructing its own."""

    def __init__(self):
        self.model_name = getattr(settings, "EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        self.default_threshold = float(getattr(settings, "EMBEDDING_MATCH_THRESHOLD", 0.6))
        self._model: Optional[SentenceTransformer] = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info(f"Loading sentence-transformer model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode(self, texts: List[str]):
        """Encode a batch of strings once. Reuse the result across multiple
        best_match_precomputed calls instead of re-encoding the same
        choice list on every lookup — encoding the whole catalogue per
        query is the main performance trap with this approach."""
        if not texts:
            return None
        return self.model.encode(texts, convert_to_tensor=True)

    def best_match(self, query: str, choices: List[str], threshold: float = None) -> Tuple[Optional[str], float]:
        """Encodes choices itself — convenient for a one-off lookup, but
        prefer best_match_precomputed when matching several queries
        against the same choice list."""
        if not query or not choices:
            return None, 0.0
        return self.best_match_precomputed(query, choices, self.encode(choices), threshold)

    def best_match_precomputed(self, query: str, choices: List[str], choice_embeddings, threshold: float = None) -> Tuple[Optional[str], float]:
        """Returns (best_choice, score) for the choice most semantically
        similar to query, or (None, score) if nothing clears the
        threshold. choice_embeddings must come from encode(choices), in
        the same order as choices."""
        if not query or not choices or choice_embeddings is None:
            return None, 0.0

        threshold = self.default_threshold if threshold is None else threshold

        query_embedding = self.model.encode(query, convert_to_tensor=True)
        scores = util.cos_sim(query_embedding, choice_embeddings)[0]

        best_idx = int(scores.argmax())
        best_score = float(scores[best_idx])

        if best_score >= threshold:
            return choices[best_idx], best_score
        return None, best_score


embeddings_service = EmbeddingsService()

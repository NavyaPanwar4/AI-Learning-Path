import os
import pickle
from app.utils.config import settings
from app.utils.logger import logger

class EmbeddingsService:
    def __init__(self):
        self.model_name = settings.EMBEDDINGS_MODEL
        self.cache_file = os.path.join(settings.APP_DATA_DIR, "embeddings_cache.pkl")
        self.cache = self._load_cache()
        self._model = None

    @property
    def model(self):
        if self._model is None:
            logger.info(f"Loading SentenceTransformer: {self.model_name}")
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _load_cache(self) -> dict:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "rb") as f:
                    return pickle.load(f)
            except Exception as e:
                logger.error(f"Error loading embeddings cache: {e}")
        return {}

    def _save_cache(self):
        try:
            with open(self.cache_file, "wb") as f:
                pickle.dump(self.cache, f)
        except Exception as e:
            logger.error(f"Error saving embeddings cache: {e}")

    def get_embedding(self, text: str):
        if text in self.cache:
            return self.cache[text]
        
        emb = self.model.encode(text)
        self.cache[text] = emb
        self._save_cache()
        return emb

    def get_embeddings(self, texts: list):
        embeddings = []
        texts_to_encode = []
        indices_to_encode = []

        for i, text in enumerate(texts):
            if text in self.cache:
                embeddings.append(self.cache[text])
            else:
                embeddings.append(None)
                texts_to_encode.append(text)
                indices_to_encode.append(i)

        if texts_to_encode:
            new_embs = self.model.encode(texts_to_encode)
            for idx, text, emb in zip(indices_to_encode, texts_to_encode, new_embs):
                self.cache[text] = emb
                embeddings[idx] = emb
            self._save_cache()

        return embeddings

embeddings_service = EmbeddingsService()

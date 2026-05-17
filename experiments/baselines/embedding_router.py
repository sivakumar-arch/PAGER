"""Baseline 4: Embedding-Based Routing.

Cosine similarity between query embedding and agent description embeddings.
Uses sentence-transformers (all-MiniLM-L6-v2).
Purpose: state-of-the-art research approach (main comparison #2).

No policy enforcement — pure semantic matching.

Expected performance (paper Section 6.1):
    Routing Accuracy:    ~74%  (better than rule-based via semantic understanding)
    Policy Compliance:   ~61%  (no enforcement — accidental alignment)
    Auth Violations:     ~22%  (no authorization check)
"""

import numpy as np

from src.models.agent import Agent
from src.utils.logger import get_logger
from experiments.baselines.base_router import BaseRouter

logger = get_logger(__name__)

# Agent descriptions for embedding — what each agent does in natural language
AGENT_DESCRIPTIONS: dict[str, str] = {
    "patient_demographics_agent": (
        "Retrieve patient demographics including name, date of birth, "
        "medical record number MRN, address, and contact information. "
        "Patient lookup and identity verification."
    ),
    "vitals_agent": (
        "Record and retrieve patient vital signs including blood pressure, "
        "heart rate, temperature, respiratory rate, oxygen saturation, "
        "weight, height, and BMI measurements."
    ),
    "labs_agent": (
        "Retrieve laboratory test results including blood tests, glucose, "
        "magnesium, HbA1c, hemoglobin, creatinine, sodium, potassium, "
        "cholesterol, and other diagnostic values."
    ),
    "medication_agent": (
        "Manage medication orders and prescriptions. Order new medications, "
        "check current medications, manage drug dosages and prescriptions "
        "for patient treatment."
    ),
    "procedure_agent": (
        "Order medical procedures, referrals, and surgeries. Schedule "
        "specialist referrals, surgical procedures, orthopedic and "
        "cardiology consultations and service requests."
    ),
}


class EmbeddingRouter(BaseRouter):
    """Routes queries using cosine similarity between query and agent embeddings.

    Lazy-loads the sentence-transformers model on first use to avoid
    import-time overhead during baseline comparison setup.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model = None
        self._agent_embeddings: dict[str, np.ndarray] = {}
        logger.info("EmbeddingRouter initialized", model=model_name)

    @property
    def name(self) -> str:
        return "Embedding-Based"

    def _load_model(self):
        """Lazy-load sentence-transformers model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self._model_name)
                logger.info("Embedding model loaded", model=self._model_name)
            except ImportError:
                raise ImportError(
                    "sentence-transformers not installed. "
                    "Run: pip install sentence-transformers"
                )

    def _get_agent_embedding(self, agent_id: str) -> np.ndarray:
        """Get or compute embedding for an agent description."""
        if agent_id not in self._agent_embeddings:
            self._load_model()
            description = AGENT_DESCRIPTIONS.get(
                agent_id,
                f"Agent for {agent_id.replace('_', ' ')}"
            )
            embedding = self._model.encode(description, convert_to_numpy=True)
            self._agent_embeddings[agent_id] = embedding
        return self._agent_embeddings[agent_id]

    def route(
        self,
        question: str,
        agents: list[Agent],
        task_type: int | None = None,
        user_role: str = "nurse",
        **kwargs,
    ) -> str:
        if not agents:
            raise ValueError("EmbeddingRouter: no agents available")

        self._load_model()

        # Encode query
        query_embedding = self._model.encode(question, convert_to_numpy=True)

        # Compute cosine similarity with each agent
        best_agent_id = None
        best_score = -1.0

        for agent in agents:
            agent_embedding = self._get_agent_embedding(agent.id)

            # Cosine similarity
            score = float(np.dot(query_embedding, agent_embedding) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(agent_embedding)
            ))

            logger.debug("Embedding similarity", agent=agent.id, score=f"{score:.4f}")

            if score > best_score:
                best_score = score
                best_agent_id = agent.id

        logger.debug(
            "Embedding selection", selected=best_agent_id, score=f"{best_score:.4f}"
        )
        return best_agent_id

"""MedAgentBench dataset loader and ground truth mapping.

Loads test_data_v2.json, samples 75 questions with balanced task coverage,
and provides ground truth agent mapping per handoff Section 8.

Ground truth mapping (Task → Agent):
    Task 1:  Patient lookup          → patient_demographics_agent
    Task 2:  Patient age             → patient_demographics_agent
    Task 3:  Record vitals           → vitals_agent
    Task 4:  Recent lab value        → labs_agent
    Task 5:  Check lab + order med   → medication_agent
    Task 6:  Average lab value       → labs_agent
    Task 7:  Most recent lab         → labs_agent
    Task 8:  Order procedure         → procedure_agent
    Task 9:  Complex workflow        → medication_agent
    Task 10: HbA1C + order if old   → labs_agent
"""

import json
import random
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Ground truth: task_type → agent_id
GROUND_TRUTH_MAP: dict[int, str] = {
    1: "patient_demographics_agent",
    2: "patient_demographics_agent",
    3: "vitals_agent",
    4: "labs_agent",
    5: "medication_agent",
    6: "labs_agent",
    7: "labs_agent",
    8: "procedure_agent",
    9: "medication_agent",
    10: "labs_agent",
}

# User role per task type (determines authorization policy evaluation)
TASK_USER_ROLES: dict[int, str] = {
    1: "nurse",
    2: "nurse",
    3: "nurse",
    4: "nurse",
    5: "doctor",
    6: "nurse",
    7: "nurse",
    8: "doctor",
    9: "doctor",
    10: "doctor",
}

# Target sample per task (7-8 per task = 75 total across 10 tasks)
SAMPLES_PER_TASK: dict[int, int] = {
    1: 8, 2: 8, 3: 7, 4: 8,
    5: 7, 6: 8, 7: 8, 8: 8,
    9: 7, 10: 8,
}  # total = 77 (includes 2 GDPR scenarios added separately)


def load_dataset(data_path: str | Path) -> list[dict]:
    """Load MedAgentBench test_data_v2.json.

    MedAgentBench field names:
        id:          "task1_1", "task2_3" etc. — task type embedded in ID
        instruction: the natural language question text
        context:     additional context (often empty)
        sol:         list of acceptable answers
        eval_MRN:    patient MRN for evaluation

    Returns:
        List of records with task_type extracted from ID.
    """
    data_path = Path(data_path)
    if not data_path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {data_path}\n"
            "Download from MedAgentBench and place in data/medagentbench/"
        )

    with open(data_path) as f:
        data = json.load(f)

    # Extract task_type from ID field (e.g. "task3_7" → task_type=3)
    import re
    for record in data:
        m = re.match(r"task(\d+)_", record.get("id", ""))
        record["task_type"] = int(m.group(1)) if m else None
        # Normalize question field name
        record["question"] = record.get("instruction", "")

    logger.info("Dataset loaded", path=str(data_path), count=len(data))
    return data


def sample_questions(
    dataset: list[dict],
    samples_per_task: dict[int, int] | None = None,
    seed: int = 42,
) -> list[dict]:
    """Sample questions with balanced task coverage.

    Args:
        dataset: Full MedAgentBench dataset (after load_dataset normalization).
        samples_per_task: Dict of task_type → n_samples. Uses default if None.
        seed: Random seed for reproducibility.

    Returns:
        Sampled list of question dicts enriched with ground_truth_agent
        and user_role fields.
    """
    if samples_per_task is None:
        samples_per_task = SAMPLES_PER_TASK

    random.seed(seed)

    # Group by task type
    by_task: dict[int, list[dict]] = {}
    for q in dataset:
        task = q.get("task_type")
        if task is not None:
            by_task.setdefault(task, []).append(q)

    sampled = []
    for task_type, n in samples_per_task.items():
        available = by_task.get(task_type, [])
        if not available:
            logger.warning(f"No questions found for task {task_type}")
            continue

        n_sample = min(n, len(available))
        chosen = random.sample(available, n_sample)

        for q in chosen:
            q_enriched = dict(q)
            q_enriched["task_type"] = task_type
            q_enriched["ground_truth_agent"] = GROUND_TRUTH_MAP[task_type]
            q_enriched["user_role"] = TASK_USER_ROLES[task_type]
            sampled.append(q_enriched)

    logger.info(
        "Questions sampled",
        total=len(sampled),
        tasks=sorted(set(q["task_type"] for q in sampled)),
    )
    return sampled


def get_gdpr_scenarios() -> list[dict]:
    """Return 2 hand-crafted GDPR evaluation scenarios.

    These are not from MedAgentBench — they test GDPR policies specifically
    to demonstrate cross-domain applicability.
    """
    return [
        {
            "id": "gdpr_001",
            "question": "Process personal data for EU patient and store results",
            "task_type": None,
            "ground_truth_agent": "eu_data_agent",
            "user_role": "data_processor",
            "user_region": "EU",
            "requires_consent": False,
            "scenario": "gdpr_data_residency",
        },
        {
            "id": "gdpr_002",
            "question": "Send marketing communication to EU patient with consent",
            "task_type": None,
            "ground_truth_agent": "marketing_agent",
            "user_role": "marketing_manager",
            "user_region": "EU",
            "requires_consent": True,
            "scenario": "gdpr_consent",
        },
    ]

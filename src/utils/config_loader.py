"""PAGER configuration loader utility.

Handles loading and validation of YAML configuration files for agent
registries and global PAGER settings. Provides clear error messages
for missing files or malformed configs.
"""

from pathlib import Path
from typing import Any

import yaml

from pager.utils.logger import get_logger

logger = get_logger(__name__)


class ConfigLoadError(Exception):
    """Raised when a configuration file cannot be loaded or parsed."""


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load and parse a YAML configuration file.

    Args:
        path: Path to the YAML file (str or Path).

    Returns:
        Parsed YAML content as a dictionary.

    Raises:
        ConfigLoadError: If file does not exist, is empty, or has invalid YAML.

    Example:
        config = load_yaml("configs/agents/healthcare_agents.yaml")
        agents = config["agents"]
    """
    file_path = Path(path)

    if not file_path.exists():
        raise ConfigLoadError(
            f"Configuration file not found: {file_path.resolve()}\n"
            f"Check that the path is correct relative to your working directory."
        )

    if not file_path.is_file():
        raise ConfigLoadError(f"Path is not a file: {file_path.resolve()}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigLoadError(f"Cannot read configuration file {file_path}: {e}") from e

    if not content.strip():
        raise ConfigLoadError(f"Configuration file is empty: {file_path}")

    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ConfigLoadError(
            f"Invalid YAML in {file_path}:\n{e}"
        ) from e

    if parsed is None:
        raise ConfigLoadError(f"Configuration file parsed as None: {file_path}")

    logger.debug(f"Loaded config from {file_path}")
    return parsed  # type: ignore[return-value]


def load_agent_config(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate an agent registry YAML file.

    Args:
        path: Path to agent YAML file (must contain top-level 'agents' key).

    Returns:
        List of agent configuration dictionaries.

    Raises:
        ConfigLoadError: If file is invalid or missing 'agents' key.
    """
    config = load_yaml(path)

    if "agents" not in config:
        raise ConfigLoadError(
            f"Agent config missing required top-level 'agents' key: {path}\n"
            f"Found keys: {list(config.keys())}"
        )

    agents = config["agents"]

    if not isinstance(agents, list):
        raise ConfigLoadError(
            f"'agents' must be a list in {path}, got {type(agents).__name__}"
        )

    if not agents:
        raise ConfigLoadError(f"'agents' list is empty in {path}")

    logger.debug(f"Loaded {len(agents)} agent(s) from {path}")
    return agents


def load_pager_config(path: str | Path = "configs/pager_config.yaml") -> dict[str, Any]:
    """Load the global PAGER configuration file.

    Args:
        path: Path to pager_config.yaml. Defaults to configs/pager_config.yaml.

    Returns:
        Parsed PAGER configuration dictionary.

    Raises:
        ConfigLoadError: If file is invalid or missing 'pager' key.
    """
    config = load_yaml(path)

    if "pager" not in config:
        raise ConfigLoadError(
            f"PAGER config missing required top-level 'pager' key: {path}"
        )

    return config["pager"]  # type: ignore[return-value]

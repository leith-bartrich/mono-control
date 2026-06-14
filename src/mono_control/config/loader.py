"""Load and validate the mono-config directory into pydantic models.

Directory-oriented: ``load_config`` takes the config *directory*. Today it reads
a single provisional ``system.json``; the marked seam below is where additional
named files get merged in once the directory layout is designed.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..paths import CONFIG_DIR, SYSTEM_FILE
from .errors import ConfigNotFoundError, ConfigParseError, ConfigValidationError
from .models import WorkspaceConfig


def _read_json(path: Path) -> Any:
    """Read and parse one JSON file, wrapping failures as ConfigError.

    Shared by every config file so the not-found / parse-error handling is
    consistent as more named files are added.
    """
    try:
        raw = path.read_text()
    except FileNotFoundError as e:
        raise ConfigNotFoundError(f"Config file not found: {path}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigParseError(f"{path} is not valid JSON: {e}") from e


def load_config(config_dir: Path | None = None) -> WorkspaceConfig:
    """Load the config directory into a validated WorkspaceConfig.

    ``config_dir`` defaults to the bind-mounted CONFIG_DIR; pass an explicit
    path to load an arbitrary directory (used in tests).
    """
    config_dir = config_dir or CONFIG_DIR
    if not config_dir.is_dir():
        raise ConfigNotFoundError(f"Config directory not found: {config_dir}")

    data = _read_json(config_dir / SYSTEM_FILE)
    # FUTURE: merge additional named files from config_dir here.

    try:
        return WorkspaceConfig.load(data)
    except ValidationError as e:
        raise ConfigValidationError(
            f"{config_dir / SYSTEM_FILE} failed validation:\n{e}"
        ) from e

"""Typed errors for the config data layer.

Callers (and the CLI) catch ``ConfigError`` to surface a clear message instead
of a raw stdlib/pydantic traceback.
"""


class ConfigError(Exception):
    """Base class for all config-loading failures."""


class ConfigNotFoundError(ConfigError):
    """The config directory or a required file within it is missing."""


class ConfigParseError(ConfigError):
    """A config file exists but is not valid JSON."""


class ConfigValidationError(ConfigError):
    """A config file parsed but did not match the expected schema."""


class ConfigVersionError(ConfigError):
    """The document's version is missing, unknown, too new, or un-migratable."""


class ConfigConflictError(ConfigError):
    """An attempt to create a config document that already exists."""


class AmbiguousNameError(ConfigError):
    """A name-or-slug lookup matched more than one repo by name.

    Carries the input and the list of candidate slugs so the CLI can render a
    helpful "matches: X, Y — pass --slug to disambiguate" message.
    """

    def __init__(self, query: str, candidate_slugs: list[str]) -> None:
        self.query = query
        self.candidate_slugs = candidate_slugs
        joined = ", ".join(candidate_slugs)
        super().__init__(
            f"name {query!r} matches: {joined} — pass --slug to disambiguate"
        )

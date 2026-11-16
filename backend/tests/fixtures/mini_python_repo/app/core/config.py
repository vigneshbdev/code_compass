"""Configuration loading."""

import os

DEFAULT_TIMEOUT = 30


def parse_config(path: str) -> dict[str, str]:
    """Parse a KEY=VALUE file into a dict, ignoring comments and blank lines."""
    result: dict[str, str] = {}
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def env_or_default(name: str, default: str) -> str:
    return os.environ.get(name, default)

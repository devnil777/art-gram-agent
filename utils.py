"""
utils.py - Utility helpers.
"""

import os
from datetime import datetime, timezone


def get_workspace_root(env_var: str = "ART_GRAM_HOME") -> str:
    """Return workspace root from environment or current working directory."""
    workspace_root = os.environ.get(env_var, "").strip()
    if workspace_root:
        workspace_root = os.path.abspath(workspace_root)
        if not os.path.isdir(workspace_root):
            raise FileNotFoundError(
                f"Environment variable {env_var} is set to '{workspace_root}', "
                f"but this directory does not exist."
            )
        return workspace_root
    return os.getcwd()


def set_workspace_root_from_env(env_var: str = "ART_GRAM_HOME") -> str:
    """Set the current working directory to the workspace root if env var is defined."""
    workspace_root = get_workspace_root(env_var)
    os.chdir(workspace_root)
    return workspace_root


def generate_run_id() -> str:
    """Generate a sortable run identifier based on UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

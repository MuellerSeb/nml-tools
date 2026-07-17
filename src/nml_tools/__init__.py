"""nml-tools package."""

from .json2nml import json_to_namelist

try:
    from ._version import __version__
except ModuleNotFoundError:  # pragma: no cover
    # package is not installed
    __version__ = "0.0.0.dev0"

__all__ = ["__version__", "json_to_namelist"]

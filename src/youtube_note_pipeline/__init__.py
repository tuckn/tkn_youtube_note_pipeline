"""YouTube raw-to-source-to-summary note pipeline."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("youtube-note-pipeline")
except PackageNotFoundError:
    __version__ = "0.3.1"

__all__ = ["__version__"]

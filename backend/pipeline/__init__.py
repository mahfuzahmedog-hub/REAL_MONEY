"""REAL_MONEY pipeline package.

Re-exports subpackage modules at the top level for backward compatibility:
    from pipeline.downloader import check_duration   # works
    from pipeline.clipper import process_clip        # works
    from pipeline.orchestrator import run_pipeline  # works
"""
import sys

from .download import downloader, transcriber, windowed, market
from .analyze import ai_analyzer, quality, subtitler
from .render import clipper, music
from . import orchestrator, config

_flat_names = ("downloader", "transcriber", "windowed", "market",
                 "ai_analyzer", "quality", "subtitler",
                 "clipper", "music")
for _name, _mod in zip(_flat_names, (downloader, transcriber, windowed, market,
                                     ai_analyzer, quality, subtitler,
                                     clipper, music)):
    sys.modules[f"pipeline.{_name}"] = _mod

__all__ = [
    "downloader", "transcriber", "windowed", "market",
    "ai_analyzer", "quality", "subtitler",
    "clipper", "music",
    "orchestrator", "config",
]

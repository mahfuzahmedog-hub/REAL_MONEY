"""Subpackage: render - ffmpeg-based final video production.

Modules:
- clipper: process_clip() - vertical crop, subtitle burn, hook overlay, music mix
- music: CC0 music picker (mood-based)
"""
from . import clipper, music

__all__ = ["clipper", "music"]

"""Portable AF3 starter layout; paths verified against the local AF3 source."""
from __future__ import annotations
import json
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "arctic-fuse-3-minimal.json"

def minimal_layout_template():
    return TEMPLATE.read_bytes()

def describe_template():
    return ("Portable Arctic Fuse 3 layout: Kodi movies and TV library, Twitch and YouTube "
            "hub roots, and generic skin playlists. Requires AF3 3.3.12+, Skin Variables "
            "2.2.9+, Texture Maker 0.2.11+, TMDb Helper 6.17.9+. Optional service roots "
            "are fallbacks until installed/authenticated; no personalized widgets or logins "
            "are included. This is not a personal export.")

def import_template(profile, backup_dir, apply_template):
    return apply_template(profile, backup_dir, minimal_layout_template())

"""Allowlisted, backup-first AF3 configuration application and rollback."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

MANIFEST = "setupwizard-backup.json"
MAX_FILE_BYTES = 2 * 1024 * 1024
TEMPLATE_SCHEMA = 1
SKIN_NODE = "addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/"
SKIN_SETTINGS = "addon_data/skin.arctic.fuse.3/settings.xml"
ALLOWED = {SKIN_NODE + name for name in (
    "skinvariables-shortcut-homewidgets.json",
    "skinvariables-shortcut-homesubmenu.json",
    "skinvariables-shortcut-1101widgets.json",
    "skinvariables-shortcut-1102widgets.json",
    "skinvariables-shortcut-1103widgets.json",
)}
ALLOWED_TARGETS = ALLOWED | {SKIN_SETTINGS}
AMBER_MENU = 'addon_data/script.skinshortcuts/skin.amber-mainmenu.DATA.xml'
POLICIES = {
    'arctic': ALLOWED_TARGETS,
    'amber': {AMBER_MENU},
    'touch': set(),  # Native touch layout; no live cached favourites.xml edits.
}
# New adapters have independent policies; old backup shapes remain valid.
COMMON_NODE_FILES = {SKIN_NODE + 'skinvariables-shortcut-' + key + 'submenu.json'
                     for key in ('1101', '1102', '1103')}
COMMON_SHORTCUTS = 'addon_data/script.skinshortcuts/'
for _profile_id in ('arctic', 'amber', 'touch'):
    _binding = 'addon_data/script.serph91p.setup/bindings-' + _profile_id + '.json'
    if _profile_id == 'arctic':
        _paths = ALLOWED_TARGETS | COMMON_NODE_FILES
    else:
        _prefix = 'skin.amber-' if _profile_id == 'amber' else ''
        _paths = {COMMON_SHORTCUTS + _prefix + group + '.DATA.xml'
                  for group in ('mainmenu', 'movies', 'series', 'twitch', 'youtube', 'livetv')}
    if _profile_id == 'touch':
        _paths.add('addon_data/skin.estuary.modv2/settings.xml')
    POLICIES[_profile_id + '-common'] = _paths | {_binding}
ALL_TARGETS = set().union(*POLICIES.values())
SAFE_SETTINGS = {
    "homeswitcher.vertical": "true",
    "homeswitcher.disablefirstwidgetfocus": "true",
    "homeswitcher.enableicons": "true",
    "HomeSwitcher.Home.Name": "Filme",
    "HomeSwitcher.Home.Shortcut.Path": "ActivateWindow(1181)",
    "HomeSwitcher.Home.Shortcut.Target": "",
    "HomeSwitcher.1101.Name": "Serien",
    "HomeSwitcher.1101.Shortcut.Path": "library://video/tvshows/",
    "HomeSwitcher.1101.Shortcut.Target": "videos",
    "HomeSwitcher.1101.Toggle": "true",
    "HomeSwitcher.1102.Name": "Twitch",
    "HomeSwitcher.1102.Shortcut.Path": "plugin://plugin.video.twitch/",
    "HomeSwitcher.1102.Shortcut.Target": "videos",
    "HomeSwitcher.1102.Toggle": "true",
    "HomeSwitcher.1103.Name": "YouTube",
    "HomeSwitcher.1103.Shortcut.Path": "plugin://plugin.video.youtube/",
    "HomeSwitcher.1103.Shortcut.Target": "videos",
    "HomeSwitcher.1103.Toggle": "true",
}

# Keep legacy SAFE_SETTINGS/template validation unchanged for old backups.
# Portable sidebar choices from the supplied LibreELEC reference, AF3 3.3.12.
ARCTIC_REFERENCE_ICONS = {
    "HomeSwitcher.Home.Icon": "special://skin/extras/icons/film.png",
    "HomeSwitcher.1101.Icon": "special://skin/extras/icons/director.png",
    "HomeSwitcher.1102.Icon": "special://skin/extras/icons/twitch.png",
    "HomeSwitcher.1103.Icon": "special://skin/extras/icons/youtube.png",
    "HomeSwitcher.1104.Icon": "special://skin/extras/icons/folder.png",
}

class LayoutConflict(ValueError):
    """The on-disk configuration no longer matches the staged transaction."""


def _relative(value: str, *, settings: bool = False) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("invalid relative path")
    p = PurePosixPath(value)
    if p.is_absolute() or str(p) != value or any(x in ("", ".", "..") for x in p.parts):
        raise ValueError("invalid relative path")
    if value not in (ALL_TARGETS if settings else ALLOWED):
        raise ValueError("template path is not allowlisted")
    return p


def _no_symlink_ancestors(path: Path) -> None:
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError("symlink path/ancestor is forbidden")


def _profile(path) -> Path:
    p = Path(os.path.abspath(os.fspath(path)))
    _no_symlink_ancestors(p)
    if not p.is_dir():
        raise ValueError("Kodi profile directory does not exist")
    return p


def _backup(path, profile: Path, *, must_exist=False) -> Path:
    p = Path(os.path.abspath(os.fspath(path)))
    expected_parent = profile / "setupwizard-backups"
    if p.parent != expected_parent or p.name in ("", ".", ".."):
        raise ValueError("backup must be a named child of profile/setupwizard-backups")
    _no_symlink_ancestors(p)
    if p == profile or p in profile.parents:
        raise ValueError("invalid backup location")
    if must_exist and not p.is_dir():
        raise ValueError("backup directory does not exist")
    if p.exists() and not p.is_dir():
        raise ValueError("backup path is not a directory")
    return p


def _target(profile: Path, rel: str) -> Path:
    p = profile.joinpath(*_relative(rel, settings=True).parts)
    _no_symlink_ancestors(p)
    if p.exists():
        st = p.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE_BYTES:
            raise ValueError("target is not a bounded regular file")
    return p


def _atomic(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _no_symlink_ancestors(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=".wizard-", dir=str(path.parent))
    try:
        if hasattr(os, 'fchmod'):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _merge_skin_settings(existing: bytes | None, settings: dict) -> bytes:
    if existing is None or not existing.strip():
        root = ET.Element("settings", {"version": "2"})
    else:
        try:
            root = ET.fromstring(existing)
        except ET.ParseError as exc:
            raise ValueError("existing Arctic Fuse settings.xml is invalid") from exc
        if root.tag != "settings":
            raise ValueError("unexpected Arctic Fuse settings root")
        if root.get("version") is None:
            root.set("version", "2")
    nodes = {}
    for node in root.findall("setting"):
        key = node.get("id")
        if key:
            nodes[key] = node
    for key, value in settings.items():
        # Kodi CSkinInfo::ParseSetting ignores nodes without an explicit type.
        # AF3 HomeSwitcher.Toggle is consumed as Skin.String; only the
        # homeswitcher.* flags below are Skin.HasSetting booleans.
        matching = [n for n in root.findall('setting') if n.get('id', '').lower() == key.lower()]
        node = matching[0] if matching else ET.SubElement(root, 'setting', {'id': key})
        for duplicate in matching[1:]:
            root.remove(duplicate)
        node.set('type', 'bool' if key.startswith('homeswitcher.') else 'string')
        node.text = value
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def validate_template(data: bytes) -> dict:
    if not isinstance(data, bytes) or len(data) > 5 * MAX_FILE_BYTES:
        raise ValueError("template exceeds safe size limit")
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict) or set(value) != {"schema", "files", "skin_settings"} or value["schema"] != TEMPLATE_SCHEMA:
        raise ValueError("unsupported template schema")
    files = value["files"]
    if not isinstance(files, list) or len(files) != len(ALLOWED):
        raise ValueError("template must contain exact allowlisted paths")
    seen = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "content"}:
            raise ValueError("invalid template entry")
        rel = str(_relative(item["path"]))
        if rel in seen:
            raise ValueError("duplicate template path")
        seen.add(rel)
        content = item["content"]
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("invalid template content")
        if not isinstance(json.loads(content), (dict, list)):
            raise ValueError("skin shortcut content must be JSON object/list")
    if seen != ALLOWED:
        raise ValueError("template path set mismatch")
    settings = value["skin_settings"]
    if not isinstance(settings, dict) or settings != SAFE_SETTINGS:
        raise ValueError("skin settings differ from the fixed safe allowlist")
    return value


def _build_stage(profile: Path, spec: dict):
    stage = []
    for item in spec["files"]:
        rel = str(_relative(item["path"]))
        target = _target(profile, rel)
        old = target.read_bytes() if target.exists() else None
        stage.append((rel, target, old, item["content"].encode("utf-8")))
    rel = SKIN_SETTINGS
    target = _target(profile, rel)
    old = target.read_bytes() if target.exists() else None
    merged = _merge_skin_settings(old, spec["skin_settings"])
    stage.append((rel, target, old, merged))
    return stage


def apply_template(profile, backup_dir, template_data) -> list[str]:
    profile = _profile(profile)
    spec = validate_template(template_data)
    return _apply_stage(profile, backup_dir, _build_stage(profile, spec), 'arctic')


def apply_payloads(profile, backup_dir, payloads: dict, policy: str) -> list[str]:
    """Internal curated adapters only; exact per-profile target policy."""
    profile = _profile(profile)
    if policy not in POLICIES or policy == 'arctic' or set(payloads) != POLICIES[policy]:
        raise ValueError('payload path set does not match fixed profile policy')
    stage = []
    for rel, new in sorted(payloads.items()):
        if not isinstance(new, bytes) or len(new) > MAX_FILE_BYTES:
            raise ValueError('invalid curated payload')
        target = _target(profile, rel)
        old = target.read_bytes() if target.exists() else None
        stage.append((rel, target, old, new))
    return _apply_stage(profile, backup_dir, stage, policy)


def _apply_stage(profile, backup_dir, stage, policy):
    backup = _backup(backup_dir, profile)
    if backup.exists():
        raise ValueError('backup destination must be new')
    if all(old == new for _, _, old, new in stage):
        return []
    backup_parent = backup.parent
    _no_symlink_ancestors(backup_parent)
    if not backup_parent.is_dir():
        raise ValueError("profile/setupwizard-backups directory must already exist")
    entries = []
    for rel, _, old, new in stage:
        entries.append({"path": rel, "existed": old is not None,
                        "old_sha256": _sha(old) if old is not None else None,
                        "new_sha256": _sha(new), "backup": "files/" + rel if old is not None else None})
    manifest = ({'schema': 1, 'files': entries} if policy == 'arctic'
                else {'schema': 4 if policy.endswith('-common') else 2, 'profile': policy, 'files': entries})
    backup.mkdir(mode=0o700)
    try:
        for (_, _, old, _), entry in zip(stage, entries):
            if old is not None:
                _atomic(backup.joinpath(*PurePosixPath(entry["backup"]).parts), old)
        manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        _atomic(backup / MANIFEST, manifest_bytes)
        # Validate the persisted manifest and complete backup before touching targets.
        _validate_manifest(profile, backup)
        if (backup / MANIFEST).read_bytes() != manifest_bytes:
            raise ValueError("backup manifest readback mismatch")
        for rel, target, old, new in stage:
            _target(profile, rel)
            current = target.read_bytes() if target.exists() else None
            if current != old:
                raise LayoutConflict(f"target changed while staging: {rel}")
        for rel, target, old, new in stage:
            current = target.read_bytes() if target.exists() else None
            if current == new:
                continue
            _atomic(target, new)
            if target.read_bytes() != new:
                raise OSError('configuration readback mismatch; backup preserved')
        return [rel for rel, _, _, _ in stage]
    except Exception:
        # Keep the complete backup for recovery after any partial mutation.
        raise


def _validate_manifest(profile: Path, backup: Path):
    profile = _profile(profile)
    backup = _backup(backup, profile, must_exist=True)
    mp = backup / MANIFEST
    _no_symlink_ancestors(mp)
    if not mp.is_file() or mp.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("missing or oversized manifest")
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError('invalid manifest')
    if set(manifest) == {'schema', 'files'} and manifest['schema'] == 1:
        policy = 'arctic'
    elif (set(manifest) == {'schema', 'profile', 'files'}
          and manifest['schema'] == 2 and manifest['profile'] in ('amber', 'touch')):
        policy = manifest['profile']
    elif (set(manifest) == {'schema', 'profile', 'files'}
          and manifest['schema'] == 4 and manifest['profile'] in
          ('arctic-common', 'amber-common', 'touch-common')):
        policy = manifest['profile']
    else:
        raise ValueError('invalid manifest schema/profile')
    allowed = POLICIES[policy]
    records = manifest['files']
    if not isinstance(records, list) or len(records) != len(allowed):
        raise ValueError("invalid manifest file list")
    seen = set()
    result = []
    for item in records:
        if not isinstance(item, dict) or set(item) != {"path", "existed", "old_sha256", "new_sha256", "backup"}:
            raise ValueError("invalid manifest entry")
        rel = str(_relative(item["path"], settings=True))
        if rel not in allowed:
            raise ValueError('manifest path does not belong to the recorded profile')
        if rel in seen:
            raise ValueError("duplicate manifest path")
        seen.add(rel)
        if not isinstance(item["existed"], bool) or not isinstance(item["new_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["new_sha256"]):
            raise ValueError("invalid manifest hash")
        target = _target(profile, rel)
        if item["existed"]:
            if item["backup"] != "files/" + rel or not isinstance(item["old_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["old_sha256"]):
                raise ValueError("invalid backup mapping")
            src = backup.joinpath(*PurePosixPath(item["backup"]).parts)
            _no_symlink_ancestors(src)
            if not src.is_file() or src.stat().st_size > MAX_FILE_BYTES or _sha(src.read_bytes()) != item["old_sha256"]:
                raise ValueError("backup missing or hash mismatch")
        elif item["backup"] is not None or item["old_sha256"] is not None:
            raise ValueError("invalid new-file backup record")
        result.append((item, target))
    if seen != allowed:
        raise ValueError("manifest path set mismatch")
    return result


def rollback(profile, backup_dir) -> list[str]:
    profile = _profile(profile)
    backup = _backup(backup_dir, profile, must_exist=True)
    records = _validate_manifest(profile, backup)
    # Full preflight: reject external drift before restoring any target. A missing
    # originally-absent target, or an already-restored old hash, is retry-safe.
    actions = []
    conflicts = []
    for item, target in records:
        current = target.read_bytes() if target.exists() else None
        old_hash = item["old_sha256"]
        new_hash = item["new_sha256"]
        if item["existed"] and current is not None and _sha(current) == old_hash:
            continue
        if not item["existed"] and current is None:
            continue
        if current is not None and _sha(current) == new_hash:
            actions.append((item, target))
        else:
            conflicts.append(item["path"])
    if conflicts:
        raise LayoutConflict("rollback left changed files untouched: " + ", ".join(conflicts))
    for item, target in actions:
        if item["existed"]:
            src = backup.joinpath(*PurePosixPath(item["backup"]).parts)
            _atomic(target, src.read_bytes())
        else:
            target.unlink()
    return [item["path"] for item, _ in actions]

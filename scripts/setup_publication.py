"""Explicit first-party trust path; never accepts upstream ZIPs or dispatch evidence.

Only the fixed Wizard builder and eight reviewed metadata files from the exact
checked-out target commit are admitted. External add-on provenance stays in
build_repository's existing immutable-artifact path.
"""
import hashlib
import types
import json
import re
import subprocess
import zipfile
from pathlib import Path

ADDON_ID = 'script.serph91p.setup'
VERSION = '0.4.4'
SOURCE_REPOSITORY = 'Serph91P/repository.serph91p'
INPUTS = ('addon.xml', 'resources', ADDON_ID, 'setup-bootstrap',
          'tools/build_setup_addon.py', 'tools/build_setup_bootstrap.py')
BOOTSTRAP_SHA256 = {
    'repository.adamsbuilds/addons.xml': 'f9334c62500b7d1269fea1cc36e7d0240f7704d2a9e7da8c065fb1b8d0a3847e',
    'repository.adamsbuilds/addons.xml.md5': '5ad4af056ee45bc3c4faf4930f5b7ab94797dabf278e5e9231a927aa4403226a',
    'repository.beta.emby.kodi/addons.xml': 'e41a546a57a44c54710b0b0b93d136ac8bea05f7386d082d507eccd34e8d6232',
    'repository.beta.emby.kodi/addons.xml.md5': 'a62ecffa1e5e5bd87a9185b1529aeb1d247766513933e46e0051a8ee1b333436',
    'repository.jurialmunkey/addons.xml': '90e092251bbc317693ed6b80668e7d8a911f73388701fe000a80c18da33874e6',
    'repository.jurialmunkey/addons.xml.md5': '8cf5589e2a8c515c5af87d6c02dabe1d5b4585588b9e5f831bcd565649327f1f',
    'repository.kodinerds/addons.xml': '5d627b0c8a815a03bb2767b69bd231e0dabe31eb3bfbaf5401889bc1bdfd7b5d',
    'repository.kodinerds/addons.xml.md5': 'ac42f99013d4dc2ac21cb1d4005885ed3cef47217a17b7f4b83a6ad2b8abdbeb',
}


def _git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def verify_checkout(root, target_commit):
    root = Path(root).absolute()
    if not isinstance(target_commit, str) or not re.fullmatch('[0-9a-f]{40}', target_commit):
        raise RuntimeError('first-party target commit must be an exact lowercase SHA')
    if _git(root, 'rev-parse', 'HEAD').decode().strip() != target_commit:
        raise RuntimeError('first-party target commit differs from checked-out HEAD')
    if Path(_git(root, 'rev-parse', '--show-toplevel').decode().strip()) != root:
        raise RuntimeError('first-party source must be the target repository root')
    entries = _git(root, 'ls-tree', '-rz', target_commit, '--', *INPUTS).split(b'\0')
    found = set()
    for entry in filter(None, entries):
        metadata, raw_path = entry.split(b'\t', 1)
        mode, kind, blob = metadata.split()
        relative = raw_path.decode('utf-8')
        parts = relative.split('/')
        if mode not in (b'100644', b'100755') or kind != b'blob' or any(p in ('', '.', '..') for p in parts):
            raise RuntimeError('unsafe first-party source member')
        path = root.joinpath(*parts)
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise RuntimeError('unsafe first-party source path')
        actual = _git(root, 'hash-object', '--', relative).strip()
        if actual != blob:
            raise RuntimeError('first-party source differs from target commit: ' + relative)
        found.add(relative)
    required = {'addon.xml', ADDON_ID + '/addon.xml', 'tools/build_setup_addon.py',
                'tools/build_setup_bootstrap.py'}
    required.update('setup-bootstrap/' + p for p in BOOTSTRAP_SHA256)
    if not required.issubset(found):
        raise RuntimeError('first-party target commit is missing required inputs')
    # Reject untracked source files too: a builder must not pick up local additions.
    if _git(root, 'ls-files', '--others', '--exclude-standard', '--', *INPUTS).strip():
        raise RuntimeError('untracked first-party source inputs')
    return root


def _load(root, name):
    path = root / 'tools' / (name + '.py')
    module = types.ModuleType('_publication_' + name)
    module.__file__ = str(path)
    # Never execute an ignored/local bytecode cache instead of checked source.
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def stage(builder, repo_root, target_commit, temp_dir, staging_repo):
    root = verify_checkout(repo_root, target_commit)
    bootstrap = _load(root, 'build_setup_bootstrap')
    bootstrap.validate_root()
    files = bootstrap.local_files(root / 'setup-bootstrap')
    if {p: hashlib.sha256(data).hexdigest() for p, data in files.items()} != BOOTSTRAP_SHA256:
        raise RuntimeError('bootstrap differs from reviewed original-repository metadata')
    wizard = _load(root, 'build_setup_addon')
    package = wizard.build(temp_dir / 'first-party')
    if package.name != ADDON_ID + '-' + VERSION + '.zip':
        raise RuntimeError('unexpected first-party package identity/version')
    with zipfile.ZipFile(package) as archive:
        for name in archive.namelist():
            if not name.startswith(ADDON_ID + '/') or any(p in ('', '.', '..') for p in name.split('/')):
                raise RuntimeError('unsafe first-party package path')
            if archive.read(name) != _git(root, 'show', target_commit + ':' + name):
                raise RuntimeError('package member differs from committed source')
    builder._check_version_monotonicity(root, ADDON_ID, VERSION)
    builder.validate_archive_topology(package, ADDON_ID, VERSION)
    addon = builder.publish_release_zip(package, ADDON_ID, VERSION, package.name, staging_repo)
    for relative, data in files.items():
        bootstrap.safe_write(staging_repo / 'setup-bootstrap' / relative, data)
    provenance = {
        'kind': 'first-party-target-source-v1', 'source_repository': SOURCE_REPOSITORY,
        'target_commit': target_commit, 'addon_id': ADDON_ID, 'addon_version': VERSION,
        'builder': 'tools/build_setup_addon.py',
        'artifact_sha256': hashlib.sha256(package.read_bytes()).hexdigest(),
        'bootstrap_sha256': BOOTSTRAP_SHA256,
    }
    (staging_repo / 'setup-source-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    verify_checkout(root, target_commit)
    return addon


def validate_site(site):
    site = Path(site)
    for relative, digest in BOOTSTRAP_SHA256.items():
        path = site / 'setup-bootstrap' / relative
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('missing or changed staged bootstrap metadata: ' + relative)

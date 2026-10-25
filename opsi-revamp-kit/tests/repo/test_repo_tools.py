"""Tests for the repository-strategy tools using throwaway local git repositories (no network)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "repo"))

import repo_hygiene as rh  # noqa: E402
import vendor_component as vc  # noqa: E402
import workspace as ws  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
# URL with embedded credentials, assembled at runtime so secret scanners stay quiet
CREDS_URL = "https://" + ":".join(["user", "not-a-real-pw"]) + "@git.example.invalid/opsi.git"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def make_repo(path: Path, files: dict[str, str], tag: str | None = None) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    for rel, text in files.items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    if tag:
        git(path, "tag", tag)
    return path


def commit_change(repo: Path, rel: str, text: str, tag: str | None = None) -> None:
    (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "commit", "-q", "-am", f"change {rel}")
    if tag:
        git(repo, "tag", tag)


# ------------------------------------------------------------------------------------------ vendoring
@pytest.fixture
def upstream(tmp_path):
    repo = make_repo(tmp_path / "upstream-src", {
        "LICENSE": "Apache License 2.0 (synthetic)\n",
        "NOTICE": "Upstream NOTICE (synthetic)\n",
        "spec/schema/a.json": '{"title": "a"}\n',
        "spec/schema/sub/b.json": '{"title": "b"}\n',
        "ingestion/LICENSE": "Collate Community License (synthetic)\n",
        "ingestion/x.py": "print('x')\n",
    }, tag="v1")
    # vendoring tool reads the upstream URL from 'origin'
    git(repo, "remote", "add", "origin", "https://example.invalid/upstream/OpenMetadata.git")
    return repo


@pytest.fixture
def product(tmp_path):
    p = tmp_path / "product"
    p.mkdir()
    return p


def add(product: Path, upstream: Path, **over) -> int:
    args = {"--upstream": str(upstream), "--project": "openmetadata", "--id": "om-schemas",
            "--source": "spec/schema", "--dest": "third_party/openmetadata/schema", "--spdx": "Apache-2.0",
            "--reason": "connector forms", "--approved-by": "arch ARCH-1"}
    args.update(over)
    argv = ["--repo-root", str(product), "add"]
    for k, v in args.items():
        argv += [k] if v is True else [k, v]
    return vc.main(argv)


def test_add_records_provenance_and_licence(upstream, product):
    assert add(product, upstream) == 0
    data = json.loads((product / "third_party/VENDORED.json").read_text())
    entry = data["components"][0]
    assert entry["upstream_ref"] == "v1" and len(entry["upstream_commit"]) == 40
    assert entry["upstream_url"] == "https://example.invalid/upstream/OpenMetadata.git"
    assert set(entry["files"]) == {"a.json", "sub/b.json"}
    assert (product / "third_party/openmetadata/LICENSE").read_text().startswith("Apache")
    assert (product / "third_party/openmetadata/NOTICE").exists()
    assert not (product / "third_party/openmetadata/schema/ingestion").exists()  # only what was asked for
    assert vc.main(["--repo-root", str(product), "verify"]) == 0


def test_undocumented_edit_fails_verify_until_marked(upstream, product, capsys):
    add(product, upstream)
    (product / "third_party/openmetadata/schema/a.json").write_text('{"title": "edited"}\n')
    assert vc.main(["--repo-root", str(product), "verify"]) == 1
    assert "changed without mark-modified" in capsys.readouterr().out
    assert vc.main(["--repo-root", str(product), "mark-modified", "--id", "om-schemas", "--note", "ui hints"]) == 0
    assert vc.main(["--repo-root", str(product), "verify"]) == 0


def test_untracked_and_deleted_files_are_detected(upstream, product, capsys):
    add(product, upstream)
    (product / "third_party/openmetadata/schema/extra.json").write_text("{}")
    (product / "third_party/openmetadata/schema/sub/b.json").unlink()
    assert vc.main(["--repo-root", str(product), "verify"]) == 1
    out = capsys.readouterr().out
    assert "untracked file added: extra.json" in out and "file deleted: sub/b.json" in out


def test_restricted_path_needs_approval_and_uses_nearest_licence(upstream, product):
    assert add(product, upstream, **{"--id": "om-ing", "--source": "ingestion",
                                     "--dest": "third_party/openmetadata/ingestion"}) == 2
    assert add(product, upstream, **{"--id": "om-ing", "--source": "ingestion", "--dest": "third_party/openmetadata/ing",
                                     "--spdx": "LicenseRef-Collate-Community-1.0", "--allow-restricted": True,
                                     "--allow-license": True, "--approval": "LEGAL-42"}) == 0
    entry = json.loads((product / "third_party/VENDORED.json").read_text())["components"][0]
    licence = (product / entry["license_file"]).read_text()
    assert "Collate" in licence  # nearest LICENSE (ingestion/LICENSE), not the repo root one


def test_non_permissive_licence_refused_without_approval(upstream, product):
    assert add(product, upstream, **{"--spdx": "GPL-3.0-only"}) == 2
    assert not (product / "third_party/VENDORED.json").exists()


def test_dirty_upstream_refused(upstream, product):
    (upstream / "spec/schema/a.json").write_text("{}")
    assert add(product, upstream) == 2


def test_destination_must_be_inside_third_party(upstream, product):
    assert add(product, upstream, **{"--dest": "apps/sneaky"}) == 2


def test_diff_upstream_and_update(upstream, product, capsys):
    add(product, upstream)
    commit_change(upstream, "spec/schema/a.json", '{"title": "a2"}\n', tag="v2")
    assert vc.main(["--repo-root", str(product), "diff-upstream", "--id", "om-schemas",
                    "--upstream", str(upstream), "--to", "v2"]) == 0
    assert "a.json" in capsys.readouterr().out
    assert vc.main(["--repo-root", str(product), "update", "--id", "om-schemas", "--upstream", str(upstream)]) == 0
    entry = json.loads((product / "third_party/VENDORED.json").read_text())["components"][0]
    assert entry["upstream_ref"] == "v2"
    assert (product / "third_party/openmetadata/schema/a.json").read_text() == '{"title": "a2"}\n'
    assert vc.main(["--repo-root", str(product), "verify"]) == 0


def test_update_refuses_to_drop_documented_modifications(upstream, product):
    add(product, upstream)
    (product / "third_party/openmetadata/schema/a.json").write_text("{}")
    vc.main(["--repo-root", str(product), "mark-modified", "--id", "om-schemas", "--note", "local tweak"])
    assert vc.main(["--repo-root", str(product), "update", "--id", "om-schemas", "--upstream", str(upstream)]) == 2


def test_notices_include_licence_and_modifications(upstream, product, tmp_path):
    add(product, upstream)
    vc.main(["--repo-root", str(product), "mark-modified", "--id", "om-schemas", "--note", "added x-opsi hints"])
    out = tmp_path / "NOTICES.md"
    assert vc.main(["--repo-root", str(product), "notices", "--out", str(out)]) == 0
    text = out.read_text()
    assert "Modified by Opsi" in text and "Apache License 2.0 (synthetic)" in text and "Upstream NOTICE" in text


# ------------------------------------------------------------------------------------------ workspace
@pytest.fixture
def remotes(tmp_path):
    src = tmp_path / "remotes-src"
    legacy = make_repo(src / "opsi", {"README.md": "legacy\n"})
    product = make_repo(src / "revamp", {"README.md": "revamp\n"})
    om = make_repo(src / "om", {"LICENSE": "Apache\n", "a.txt": "1\n"}, tag="2.0.6-release")
    commit_change(om, "a.txt", "2\n")  # main moves past the pinned tag
    kit = make_repo(src / "kit", {"START_HERE.md": "kit\n"})
    bare = tmp_path / "remotes"
    bare.mkdir()
    urls = {}
    for name, repo in {"opsi": legacy, "revamp": product, "om": om, "kit": kit}.items():
        target = bare / f"{name}.git"
        git(tmp_path, "clone", "-q", "--bare", str(repo), str(target))
        urls[name] = target.as_posix()
    return urls


def manifest(tmp_path: Path, urls: dict[str, str], **override) -> Path:
    data = {"root": (tmp_path / "workspaces").as_posix(), "repos": [
        {"name": "opsi-baseline-snapshot", "dir": "legacy/opsi-baseline-snapshot", "url": urls["opsi"], "role": "readonly"},
        {"name": "opsi-enterprise-revamp", "dir": "product/opsi-enterprise-revamp", "url": urls["revamp"],
         "role": "product", "extra_remotes": [{"name": "legacy-opsi", "url": urls["opsi"], "push": False}]},
        {"name": "openmetadata", "dir": "upstream/OpenMetadata", "url": urls["om"], "role": "upstream",
         "ref": "2.0.6-release"},
        {"name": "opsi-revamp-kit", "dir": "reference/opsi-revamp-kit", "url": urls["kit"], "role": "reference"},
    ]}
    data.update(override)
    path = tmp_path / "workspace.json"
    path.write_text(json.dumps(data))
    return path


def test_workspace_init_and_verify(tmp_path, remotes, capsys):
    m = manifest(tmp_path, remotes)
    assert ws.main(["init", "--manifest", str(m)]) == 0
    root = tmp_path / "workspaces"
    assert git(root / "legacy/opsi-baseline-snapshot", "remote", "get-url", "--push", "origin") == ws.DISABLED_PUSH
    assert git(root / "upstream/OpenMetadata", "remote", "get-url", "--push", "origin") == ws.DISABLED_PUSH
    assert git(root / "product/opsi-enterprise-revamp", "remote", "get-url", "--push", "legacy-opsi") == ws.DISABLED_PUSH
    assert git(root / "upstream/OpenMetadata", "describe", "--tags") == "2.0.6-release"
    assert ws.main(["verify", "--manifest", str(m)]) == 0
    assert ws.main(["init", "--manifest", str(m)]) == 0  # idempotent


def test_workspace_verify_catches_policy_violations(tmp_path, remotes, capsys):
    m = manifest(tmp_path, remotes)
    ws.main(["init", "--manifest", str(m)])
    root = tmp_path / "workspaces"
    git(root / "legacy/opsi-baseline-snapshot", "remote", "set-url", "--push", "origin", remotes["opsi"])  # re-enable push
    git(root / "upstream/OpenMetadata", "checkout", "-q", "main")                                       # drift off the pin
    (root / "reference/opsi-revamp-kit/START_HERE.md").write_text("edited")                             # dirty reference
    assert ws.main(["verify", "--manifest", str(m)]) == 1
    out = capsys.readouterr().out
    assert "must be read-only" in out and "not at pinned ref" in out and "local changes" in out


def test_product_origin_must_not_be_legacy(tmp_path, remotes, capsys):
    m = manifest(tmp_path, remotes)
    ws.main(["init", "--manifest", str(m)])
    git(tmp_path / "workspaces/product/opsi-enterprise-revamp", "remote", "set-url", "origin", remotes["opsi"])
    assert ws.main(["verify", "--manifest", str(m)]) == 1
    assert "product origin points at a read-only" in capsys.readouterr().out


def test_manifest_validation(tmp_path, remotes):
    bad = manifest(tmp_path, remotes)
    data = json.loads(bad.read_text())
    data["repos"][0]["url"] = CREDS_URL
    bad.write_text(json.dumps(data))
    assert ws.main(["verify", "--manifest", str(bad)]) == 2
    data["repos"][0]["url"] = remotes["opsi"]
    data["repos"].append(dict(data["repos"][1], name="second-product"))
    bad.write_text(json.dumps(data))
    assert ws.main(["verify", "--manifest", str(bad)]) == 2


def test_upstream_updates_lists_newer_tags(tmp_path, remotes, capsys):
    src_om = tmp_path / "om-dev"
    git(tmp_path, "clone", "-q", remotes["om"], str(src_om))
    git(src_om, "tag", "2.0.7-release")
    git(src_om, "push", "-q", "origin", "2.0.7-release")
    m = manifest(tmp_path, remotes)
    ws.main(["init", "--manifest", str(m)])
    capsys.readouterr()
    assert ws.main(["upstream-updates", "--manifest", str(m)]) == 0
    assert "2.0.7-release" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_mirror_script_copies_branches_and_tags_only(tmp_path, remotes):
    mirror = tmp_path / "mirror.git"
    git(tmp_path, "init", "-q", "--bare", str(mirror))
    script = (ROOT / "scripts/repo/mirror_upstream.sh").as_posix()
    bash = shutil.which("bash")  # full path: a bare "bash" can resolve to the WSL stub on Windows
    done = subprocess.run([bash, script, remotes["om"], mirror.as_posix(), (tmp_path / "cache").as_posix()],
                          capture_output=True, text=True, env=ENV)
    assert done.returncode == 0, done.stderr
    assert "2.0.6-release" in git(mirror, "tag")
    assert "main" in git(mirror, "branch")
    bad = subprocess.run([bash, script, CREDS_URL, mirror.as_posix()],
                         capture_output=True, text=True)
    assert bad.returncode == 2


# ------------------------------------------------------------------------------------------ hygiene
CLEAN_FILES = {
    "README.md": "product\n",
    "LICENSE": "proprietary\n",
    "apps/web/package.json": "{}\n",
    "apps/web/package-lock.json": "{}\n",
    "config/app.env.example": "KEY=\n",
    "third_party/VENDORED.json": json.dumps({"version": 1, "components": [
        {"id": "om-schemas", "dest_path": "third_party/openmetadata/schema"}]}),
    "third_party/README.md": "vendored code\n",
    "third_party/openmetadata/LICENSE": "Apache\n",
    "third_party/openmetadata/schema/a.json": "{}\n",
}


def test_hygiene_clean_repo_passes(tmp_path):
    repo = make_repo(tmp_path / "clean", CLEAN_FILES)
    assert rh.main(["--repo-root", str(repo)]) == 0


def test_hygiene_flags_everything_that_makes_a_repo_unmanageable(tmp_path, capsys):
    repo = make_repo(tmp_path / "messy", {
        **CLEAN_FILES,
        ".gitmodules": '[submodule "x"]\n',
        ".env": "SECRET=1\n",
        "apps/admin/package.json": "{}\n",
        "lib/copied-from-upstream/LICENSE": "MIT\n",
        "third_party/stray.js": "1\n",
        "node_modules/left-pad/index.js": "1\n",
        "big.bin": "x" * (2 * 1024 * 1024),
    })
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},ext/OpenMetadata")
    assert rh.main(["--repo-root", str(repo)]) == 1
    out = capsys.readouterr().out
    for expected in (".gitmodules is tracked", "embedded repository (gitlink): ext/OpenMetadata",
                     "environment file tracked", "package.json without a committed lockfile: apps/admin/package.json",
                     "outside third_party/ (copied upstream code?): lib/copied-from-upstream/LICENSE",
                     "not registered in VENDORED.json: third_party/stray.js",
                     "artefact or key material tracked: node_modules/left-pad/index.js", "large file"):
        assert expected in out, expected
    assert "config/app.env.example" not in out and "third_party/openmetadata" not in out
    assert not any("large file" in p for p in rh.check(repo, 1024, ["big.bin"]))

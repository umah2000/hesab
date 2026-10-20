"""Build a customer release package: nextcam-<version>.zip (docs/install/upgrade.md).

    python tools/release/build_release.py --out dist            # uses frontend/dist as built
    python tools/release/build_release.py --out dist --build-frontend --wheels

Contents: backend (app, migrations), packages/nextcam-core, device-agent, the built web
app, deploy/ (Windows scripts, Caddyfile), docs/install, VERSION and SHA256SUMS.
--wheels adds Windows (cp313, win_amd64) wheels so a server without internet can install.
Never included: tests, tools/license (vendor only), .env files, virtualenvs, caches.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INCLUDE = [
    ("backend/app", "backend/app"),
    ("backend/migrations", "backend/migrations"),
    ("backend/alembic.ini", "backend/alembic.ini"),
    ("backend/pyproject.toml", "backend/pyproject.toml"),
    ("backend/scripts/load_test.py", "backend/scripts/load_test.py"),
    ("packages/nextcam-core/nextcam_core", "packages/nextcam-core/nextcam_core"),
    ("packages/nextcam-core/pyproject.toml", "packages/nextcam-core/pyproject.toml"),
    ("device-agent/nextcam_agent", "device-agent/nextcam_agent"),
    ("device-agent/pyproject.toml", "device-agent/pyproject.toml"),
    ("frontend/dist", "frontend-dist"),
    ("deploy", "deploy"),
    ("docs/install", "docs/install"),
]
SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SKIP_FILES = re.compile(r"(^\.env$|\.pyc$|\.pyo$|\.log$|\.partial$|\.pem$|\.nclic$)")
PY = "3.13"


def version() -> str:
    text = (ROOT / "backend/app/version.py").read_text("utf-8")
    m = re.search(r'^VERSION = "([^"]+)"', text, re.M)
    if not m:
        raise SystemExit("VERSION not found in backend/app/version.py")
    v = m.group(1)
    pyproject = tomllib.loads((ROOT / "backend/pyproject.toml").read_text("utf-8"))
    if pyproject["project"]["version"] != v:
        raise SystemExit(
            f"version mismatch: app/version.py {v} vs pyproject {pyproject['project']['version']}"
        )
    return v


def copy_tree(src: Path, dst: Path) -> None:
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in rel.parts):
            continue
        if p.is_dir() or SKIP_FILES.search(p.name):
            continue
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)


def requirements() -> list[str]:
    reqs: list[str] = ["setuptools>=75", "wheel", "pip"]
    for proj, extras in (
        ("backend", []),
        ("device-agent", ["windows", "serial"]),
        ("packages/nextcam-core", []),
    ):
        data = tomllib.loads((ROOT / proj / "pyproject.toml").read_text("utf-8"))["project"]
        deps = list(data.get("dependencies", []))
        for e in extras:
            deps += data.get("optional-dependencies", {}).get(e, [])
        # Markers such as sys_platform == 'win32' would be judged on this build machine.
        reqs += [d.split(";")[0].strip() for d in deps if not d.lower().startswith("nextcam-core")]
    return sorted(set(reqs))


def download_wheels(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "pip", "download", "--quiet", "--dest", str(dest),
        "--only-binary=:all:", "--platform", "win_amd64", "--python-version", PY,
        "--implementation", "cp", *requirements(),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)  # noqa: S603 - fixed argument list


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default="dist")
    ap.add_argument("--build-frontend", action="store_true")
    ap.add_argument("--wheels", action="store_true")
    a = ap.parse_args()

    v = version()
    if a.build_frontend:
        npm = shutil.which("npm") or "npm"
        subprocess.run([npm, "ci"], cwd=ROOT / "frontend", check=True)  # noqa: S603
        subprocess.run([npm, "exec", "--", "vite", "build"], cwd=ROOT / "frontend", check=True)  # noqa: S603
    if not (ROOT / "frontend/dist/index.html").exists():
        raise SystemExit(
            "frontend/dist is missing: build it (npx vite build) or pass --build-frontend"
        )

    out = Path(a.out).resolve()
    stage = out / f"nextcam-{v}"
    if stage.exists():
        shutil.rmtree(stage)
    for src, dst in INCLUDE:
        copy_tree(ROOT / src, stage / dst)
    if (stage / "tools").exists() or any(stage.rglob("nextcam_license.py")):
        raise SystemExit("the vendor license tool must never be packaged")
    if a.wheels:
        download_wheels(stage / "wheels")
    (stage / "VERSION").write_text(v + "\n", "utf-8")
    sums = []
    for p in sorted(stage.rglob("*")):
        if p.is_file():
            sums.append(
                f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(stage).as_posix()}"
            )
    (stage / "SHA256SUMS").write_text("\n".join(sums) + "\n", "utf-8")

    archive = out / f"nextcam-{v}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, f"nextcam-{v}/{p.relative_to(stage).as_posix()}")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / f"nextcam-{v}.zip.sha256").write_text(f"{digest}  {archive.name}\n", "utf-8")
    print(f"{archive} ({archive.stat().st_size // 1024} KB, {len(sums)} files)")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

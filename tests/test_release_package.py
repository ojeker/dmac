"""Smoke tests for the manual Home Assistant release archive."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import zipfile


def test_release_archive_contains_an_importable_custom_component(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    output_dir = tmp_path / "release"

    subprocess.run(
        [str(project_root / "scripts" / "build-ha-release.sh"), str(output_dir)],
        check=True,
        cwd=project_root,
    )

    archive = output_dir / "dmac-0.1.0.zip"
    with zipfile.ZipFile(archive) as release:
        names = set(release.namelist())
        assert "custom_components/dmac/manifest.json" in names
        assert "custom_components/dmac/dm_accounting/__init__.py" in names
        assert "custom_components/dmac/ha_adapter/__init__.py" in names
        release.extractall(tmp_path / "extracted")

    extracted_root = tmp_path / "extracted"
    environment = os.environ | {"PYTHONPATH": str(extracted_root)}
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import custom_components.dmac, dm_accounting, ha_adapter",
        ],
        check=True,
        cwd=extracted_root,
        env=environment,
    )

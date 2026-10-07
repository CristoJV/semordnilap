import tomllib
from pathlib import Path


def test_public_command_surface_contains_exactly_four_scripts():
    project_root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert metadata["project"]["scripts"] == {
        "sp_corpus": "semordnilap.corpus.cli:main",
        "sp_tag": "semordnilap.tagging.cli:main",
        "sp_ngrams": "semordnilap.ngrams.cli.extract:main",
        "sp_semord": "semordnilap.search.cli.find_ngrams:main",
    }

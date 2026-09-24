from pathlib import Path

from config import find_repository_env_file


def test_find_repository_env_file_returns_none_for_container_layout(tmp_path: Path) -> None:
    source_file = tmp_path / "app" / "src" / "config.py"
    source_file.parent.mkdir(parents=True)
    source_file.touch()

    assert find_repository_env_file(source_file) is None


def test_find_repository_env_file_finds_an_ancestor_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.touch()
    source_file = tmp_path / "apps" / "backend" / "src" / "config.py"
    source_file.parent.mkdir(parents=True)
    source_file.touch()

    assert find_repository_env_file(source_file) == env_file

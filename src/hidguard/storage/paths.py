from pathlib import Path


def get_db_path() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir / "hidguard.db"



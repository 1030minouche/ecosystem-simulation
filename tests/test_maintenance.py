"""Tests pour engine/maintenance.py — purge des .db de runs/."""

from ecosim.engine.maintenance import purge_runs


def test_purge_runs_nonexistent_dir_is_noop(tmp_path):
    kept, deleted = purge_runs(tmp_path / "missing", keep=5)
    assert (kept, deleted) == (0, 0)


def test_purge_runs_empty_dir_is_noop(tmp_path):
    kept, deleted = purge_runs(tmp_path, keep=5)
    assert (kept, deleted) == (0, 0)


def test_purge_runs_keeps_n_most_recent(tmp_path):
    """Garde les `keep` plus récents (mtime décroissant), supprime le reste."""
    files = []
    for i in range(7):
        f = tmp_path / f"run_{i}.db"
        f.write_bytes(b"x" * 1024)
        # mtime explicite pour ordonner sans surprise
        t = 1_000_000 + i * 60
        f.touch()
        import os
        os.utime(f, (t, t))
        files.append(f)
    kept, deleted = purge_runs(tmp_path, keep=3)
    assert kept == 3
    assert deleted == 4
    survivors = sorted(tmp_path.glob("*.db"))
    # Les 3 derniers (indices 4, 5, 6) doivent survivre
    assert {p.name for p in survivors} == {"run_4.db", "run_5.db", "run_6.db"}


def test_purge_runs_keep_larger_than_count(tmp_path):
    """Si keep > nb de .db, rien n'est supprimé."""
    for i in range(3):
        (tmp_path / f"run_{i}.db").write_bytes(b"x")
    kept, deleted = purge_runs(tmp_path, keep=10)
    assert kept == 3
    assert deleted == 0


def test_purge_runs_only_targets_db_files(tmp_path):
    """Les fichiers non-.db ne sont pas touchés."""
    (tmp_path / "old.db").write_bytes(b"x")
    (tmp_path / "another.db").write_bytes(b"x")
    keep_me = tmp_path / "notes.txt"
    keep_me.write_text("important")
    kept, deleted = purge_runs(tmp_path, keep=0)
    assert kept == 0
    assert deleted == 2
    assert keep_me.exists()

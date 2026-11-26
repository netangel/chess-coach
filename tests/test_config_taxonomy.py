from pipeline.config import load_config, load_token
from pipeline.taxonomy import load_taxonomy, skill


def test_repo_config_loads():
    cfg = load_config()
    assert cfg.lichess.username
    assert cfg.training.main_perf in cfg.training.tracked_perfs
    assert cfg.review.max_chapters < 64


def test_taxonomy_keys_and_urls():
    skills = load_taxonomy()
    assert "tactics.fork" in skills and "middlegame.time-management" in skills
    assert skill("tactics.fork").url == "https://lichess.org/training/fork"
    assert skill("endgame.rook").url == "https://lichess.org/training/rookEndgame"
    assert skill("strategy.prophylaxis").url is None


def test_token_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LICHESS_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nLICHESS_TOKEN='lip_test'\n")
    assert load_token(env) == "lip_test"
    monkeypatch.setenv("LICHESS_TOKEN", "lip_env")
    assert load_token(env) == "lip_env"

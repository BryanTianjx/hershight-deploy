from pathlib import Path

import yaml

from hindsight_deploy.app import get_compose_file, get_project_name
from hindsight_deploy.memory.provisioner import MANIFEST_ROOT, load_manifest


def test_compose_profiles_exist_and_parse():
    for mode in ("basic", "production"):
        compose_file = get_compose_file(mode)
        assert compose_file.is_file()
        parsed = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        assert "hindsight" in parsed["services"]


def test_production_uses_external_postgres_url():
    compose_file = get_compose_file("production")
    parsed = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    env = parsed["services"]["hindsight"]["environment"]
    assert "HINDSIGHT_API_DATABASE_URL" in env
    assert "HINDSIGHT_MODE" not in env
    assert "./init/001-enable-vector.sql:/docker-entrypoint-initdb.d/001-enable-vector.sql:ro" in parsed["services"]["db"]["volumes"]


def test_manifest_root_and_example_bank_are_portable():
    assert MANIFEST_ROOT.is_dir()
    specs = load_manifest()
    assert [spec.bank_id for spec in specs] == ["example-project"]
    assert (MANIFEST_ROOT / "default" / "seed.md").is_file()
    assert specs[0].template_path == MANIFEST_ROOT / "default" / "seed.md"
    assert specs[0].template_path.is_file()


def test_project_names_match_compose_files():
    assert get_project_name("basic") == "hindsight"
    assert get_project_name("production") == "hindsight-prod"

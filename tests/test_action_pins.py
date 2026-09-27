from unittest import mock

from scripts import check_action_pins


def test_unpinned_actions_rejects_mutable_remote_references():
    text = "steps:\n  - uses: actions/checkout@v7\n  - uses: owner/action@main\n"
    assert check_action_pins.unpinned_actions(text, "workflow.yml") == [
        "workflow.yml:2: actions/checkout@v7",
        "workflow.yml:3: owner/action@main",
    ]


def test_unpinned_actions_allows_sha_local_and_docker_references():
    sha = "a" * 40
    text = f"steps:\n  - uses: owner/action@{sha}\n  - uses: ./local\n  - uses: docker://alpine:3\n"
    assert check_action_pins.unpinned_actions(text, "workflow.yml") == []


def test_check_workflows_reads_yaml_extensions(tmp_path):
    (tmp_path / "one.yml").write_text("- uses: owner/action@v1\n", encoding="utf-8")
    (tmp_path / "two.yaml").write_text(
        f"- uses: owner/action@{'b' * 40}\n", encoding="utf-8"
    )
    assert check_action_pins.check_workflows(tmp_path) == [
        f"{tmp_path / 'one.yml'}:1: owner/action@v1"
    ]


def test_main_reports_success_and_failure(tmp_path, capsys):
    assert check_action_pins.main([str(tmp_path)]) == 0
    (tmp_path / "bad.yml").write_text("uses: owner/action@v1\n", encoding="utf-8")
    assert check_action_pins.main([str(tmp_path)]) == 1
    assert "full commit SHA" in capsys.readouterr().err
    with mock.patch.object(
        check_action_pins, "check_workflows", side_effect=OSError("unreadable")
    ):
        assert check_action_pins.main([str(tmp_path)]) == 2
    assert "unreadable" in capsys.readouterr().err

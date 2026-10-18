from pathlib import Path

from engine.cli import main


ROOT = Path(__file__).parents[1]
ECHO_QUAY = ROOT / "worlds" / "echo-quay"
BLACK_PINE = ROOT / "worlds" / "black-pine-ridge"


def test_run_prints_a_chapter_without_debug_payload(capsys):
    assert main(["run", str(ECHO_QUAY)]) == 0

    output = capsys.readouterr().out
    assert output.startswith("回声码头\n")
    assert "# " in output
    assert '"ok"' not in output
    assert "event_count" not in output
    assert "--ticks" not in output


def test_run_prints_the_second_sample_world(capsys):
    assert main(["run", str(BLACK_PINE)]) == 0

    output = capsys.readouterr().out
    assert output.startswith("黑松岭雨夜\n")
    assert "# " in output


def test_help_lists_usage_without_internal_commands(capsys):
    assert main(["help"]) == 0

    output = capsys.readouterr().out
    assert "run" in output
    assert "worlds/echo-quay" in output
    assert "scripts/world.py" not in output
    assert "--ticks" not in output


def test_help_run_describes_the_package_argument(capsys):
    assert main(["help", "run"]) == 0

    output = capsys.readouterr().out
    assert "世界包目录" in output
    assert "--ticks" not in output


def test_run_reports_a_missing_package_in_plain_text(tmp_path, capsys):
    assert main(["run", str(tmp_path / "missing-world")]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "event_count" not in captured.err
    assert '"ok"' not in captured.err

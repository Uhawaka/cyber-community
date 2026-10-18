from pathlib import Path

import main


PACKAGE = (
    Path(__file__).resolve().parents[1]
    / "worlds"
    / "echo-quay"
)


def test_main_proxies_directory_package_validation(capsys):
    assert main.main(["validate", str(PACKAGE)]) == 0
    assert '"package_id": "echo-quay"' in capsys.readouterr().out

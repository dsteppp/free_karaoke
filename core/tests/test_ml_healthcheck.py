from unittest.mock import MagicMock, patch

from ml_healthcheck import check_ml_runtime


def test_check_ml_runtime_ok_when_torch_works():
    fake_result = MagicMock(returncode=0, stdout="OK\n", stderr="")
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        ok, detail = check_ml_runtime(python_exe="python3", cwd=".", timeout=5)
    assert ok is True
    assert detail == ""
    mock_run.assert_called_once()


def test_check_ml_runtime_fails_when_torch_broken():
    fake_result = MagicMock(
        returncode=1,
        stdout="",
        stderr="ImportError: libhsa-runtime64.so: cannot open shared object file",
    )
    with patch("subprocess.run", return_value=fake_result):
        ok, detail = check_ml_runtime(python_exe="python3", cwd=".", timeout=5)
    assert ok is False
    assert "libhsa-runtime64" in detail


def test_check_ml_runtime_fails_on_missing_ok_marker():
    # returncode == 0, но вывод не содержит "OK" — подозрительно, считаем сбоем
    fake_result = MagicMock(returncode=0, stdout="", stderr="")
    with patch("subprocess.run", return_value=fake_result):
        ok, detail = check_ml_runtime(python_exe="python3", cwd=".", timeout=5)
    assert ok is False


def test_check_ml_runtime_handles_timeout():
    import subprocess as sp
    with patch("subprocess.run", side_effect=sp.TimeoutExpired(cmd="python3", timeout=5)):
        ok, detail = check_ml_runtime(python_exe="python3", cwd=".", timeout=5)
    assert ok is False
    assert "тайм-аут" in detail.lower() or "timeout" in detail.lower()

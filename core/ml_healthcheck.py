"""
ml_healthcheck.py — проверка работоспособности PyTorch-рантайма (torch),
выполняется В ОТДЕЛЬНОМ ПОДПРОЦЕССЕ.

Не импортирует torch в этом модуле и не должна вызываться иначе как через
subprocess — именно смешение импорта torch с процессом Qt-окна ломало
GPU-контекст (см. core/tests/test_launcher_isolation.py). Цель этого
модуля — не чинить проблему, а сделать её диагностируемой: если venv
рассинхронизировался с системным ROCm/CUDA после обновления ОС, приложение
должно написать в лог понятную причину вместо непонятного нативного краша.
"""
import subprocess

_PROBE_CODE = "import torch; torch.zeros(1) + 1; print('OK')"


def check_ml_runtime(python_exe: str, cwd: str, timeout: float = 20.0) -> tuple[bool, str]:
    """
    Запускает минимальную проверку torch в изолированном подпроцессе.
    Возвращает (ok, detail). detail — пусто при успехе, иначе диагностика
    (обрезанный stderr дочернего процесса).
    """
    try:
        result = subprocess.run(
            [python_exe, "-c", _PROBE_CODE],
            cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"Проверка ML-рантайма превысила тайм-аут ({timeout}с)."
    except Exception as e:
        return False, f"Не удалось запустить проверку ML-рантайма: {e}"

    if result.returncode == 0 and "OK" in result.stdout:
        return True, ""

    detail = (result.stderr or result.stdout or "").strip()
    return False, detail[-500:]

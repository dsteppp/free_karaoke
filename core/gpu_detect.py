"""
gpu_detect.py — Каскадное определение GPU для AppImage.
Возвращает: "nvidia", "amd", "cpu"

Проверки выполняются по порядку до первого совпадения.
Все проверки безопасны — не вызывают побочных эффектов.
"""
import os
import subprocess
import logging

log = logging.getLogger("karaoke.gpu_detect")


def _run_cmd(cmd: list[str], timeout: int = 3) -> tuple[int, str]:
    """Безопасный запуск команды. Возвращает (returncode, stdout)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return -1, ""


def _check_nvidia_smis() -> bool:
    """nvidia-smi — наличие драйверов NVIDIA."""
    rc, _ = _run_cmd(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    return rc == 0


def _check_nvidia_dev() -> bool:
    """Наличие устройств /dev/nvidia*."""
    try:
        return any(
            f.startswith("nvidia") for f in os.listdir("/dev")
        )
    except OSError:
        return False


def _check_lspci_nvidia() -> bool:
    """lspci | grep -i nvidia."""
    rc, out = _run_cmd(["lspci"])
    if rc != 0:
        return False
    return "nvidia" in out.lower() or "3d controller" in out.lower()


def _check_rocm_smi() -> bool:
    """rocm-smi — наличие драйверов AMD ROCm."""
    rc, _ = _run_cmd(["rocm-smi", "--showproductname"])
    return rc == 0


def _check_amd_kfd() -> bool:
    """Наличие /dev/kfd (AMD GPU compute device)."""
    return os.path.exists("/dev/kfd")


def _check_lspci_amd() -> bool:
    """lspci | grep -i amd|radeon."""
    rc, out = _run_cmd(["lspci"])
    if rc != 0:
        return False
    lower = out.lower()
    return "amd" in lower or "radeon" in lower or "advanced micro devices" in lower


def _check_lsmod_nvidia() -> bool:
    """lsmod | grep nvidia — загружен ли модуль ядра."""
    rc, out = _run_cmd(["lsmod"])
    if rc != 0:
        return False
    return "nvidia" in out.lower()


def _check_lsmod_amdgpu() -> bool:
    """lsmod | grep amdgpu."""
    rc, out = _run_cmd(["lsmod"])
    if rc != 0:
        return False
    return "amdgpu" in out.lower()


def _check_nvidia_env() -> bool:
    """Переменные окружения NVIDIA."""
    return "CUDA_HOME" in os.environ or "CUDA_PATH" in os.environ


def _check_amd_rocm_env() -> bool:
    """Переменные окружения AMD ROCm."""
    return "ROCM_PATH" in os.environ or "ROCM_HOME" in os.environ


def detect_gpu() -> str:
    """
    Каскадное определение GPU.
    Возвращает: "nvidia", "amd", "cpu"

    Порядок проверок NVIDIA:
      1. nvidia-smi
      2. /dev/nvidia*
      3. lspci nvidia
      4. lsmod nvidia
      5. CUDA env vars

    Порядок проверок AMD:
      1. rocm-smi
      2. /dev/kfd
      3. lspci amd/radeon
      4. lsmod amdgpu
      5. ROCm env vars
    """
    log.info("🔍 Определение GPU...")

    # ── NVIDIA checks ──
    checks_nvidia = [
        ("nvidia-smi", _check_nvidia_smis),
        ("/dev/nvidia*", _check_nvidia_dev),
        ("lspci nvidia", _check_lspci_nvidia),
        ("lsmod nvidia", _check_lsmod_nvidia),
        ("CUDA env", _check_nvidia_env),
    ]
    for name, check_fn in checks_nvidia:
        try:
            if check_fn():
                log.info("   ✅ NVIDIA обнаружен (%s)", name)
                return "nvidia"
        except Exception as e:
            log.debug("   Проверка %s: %s", name, e)

    # ── AMD checks ──
    checks_amd = [
        ("rocm-smi", _check_rocm_smi),
        ("/dev/kfd", _check_amd_kfd),
        ("lspci amd", _check_lspci_amd),
        ("lsmod amdgpu", _check_lsmod_amdgpu),
        ("ROCm env", _check_amd_rocm_env),
    ]
    for name, check_fn in checks_amd:
        try:
            if check_fn():
                log.info("   ✅ AMD обнаружен (%s)", name)
                return "amd"
        except Exception as e:
            log.debug("   Проверка %s: %s", name, e)

    log.info("   🖥️ GPU не обнаружен — CPU режим")
    return "cpu"


if __name__ == "__main__":
    gpu = detect_gpu()
    print(gpu)

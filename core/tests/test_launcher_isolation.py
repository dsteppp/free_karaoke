import ast
from pathlib import Path

# Модули, которые тянут за собой torch (напрямую или транзитивно).
# Ни один из них не должен импортироваться на уровне синтаксиса launcher.py —
# только внутри строк, передаваемых в subprocess.run([sys.executable, "-c", ...]).
FORBIDDEN_MODULES = {
    "torch",
    "ai_pipeline",
    "karaoke_aligner",
    "tasks",
    "aligner_orchestra",
    "aligner_acoustics",
    "aligner_utils",
}

LAUNCHER_PATH = Path(__file__).resolve().parent.parent / "launcher.py"


def _imported_module_names(source: str) -> set[str]:
    tree = ast.parse(source, filename=str(LAUNCHER_PATH))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_launcher_never_imports_ml_modules_in_main_process():
    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    imported = _imported_module_names(source)
    offending = imported & FORBIDDEN_MODULES
    assert not offending, (
        f"core/launcher.py импортирует {offending} на уровне синтаксиса. "
        "launcher.py — ГЛАВНЫЙ процесс, в нём создаётся Qt/WebEngine-окно. "
        "Импорт torch (и модулей, тянущих его) в этом процессе может "
        "инициализировать GPU-контекст (ROCm/CUDA) и сломать EGL/Vulkan для "
        "всего процесса (см. инцидент 18.09.2026: 'Failed to get system egl "
        "display', 'Could not initialize GLX'). Такой код должен запускаться "
        "в изолированном подпроцессе: "
        "subprocess.run([sys.executable, '-c', '...'])."
    )

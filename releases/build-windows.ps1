# ═══════════════════════════════════════════════════════════════════
# Free Karaoke — Windows Portable Build (PyInstaller)
# ═══════════════════════════════════════════════════════════════════
# Статус: ПОДГОТОВКА / TODO
#
# Этот скрипт требует доработки для полной сборки.
# Текущая версия основана на desktop/windows/ (удалена при реорганизации).
#
# requirements:
#   • Windows 10/11
#   • Python 3.11
#   • PowerShell 5+
#
# Для полной сборки используйте скрипт из старой папки desktop/windows/
# или доработайте этот скрипт на основе build-appimage.sh логики.
# ═══════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "🪟  Free Karaoke — Windows Build (TODO)" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "⚠️  Этот скрипт находится в стадии разработки." -ForegroundColor Yellow
Write-Host ""
Write-Host "Для сборки Windows-версии:" -ForegroundColor White
Write-Host "  1. Убедитесь что Python 3.11 установлен" -ForegroundColor DarkGray
Write-Host "  2. Скопируйте core/requirements.txt и адаптируйте под Windows" -ForegroundColor DarkGray
Write-Host "  3. Используйте PyInstaller:" -ForegroundColor DarkGray
Write-Host ""
Write-Host "     python -m venv build-venv" -ForegroundColor Gray
Write-Host "     build-venv\Scripts\activate" -ForegroundColor Gray
Write-Host "     pip install -r core\requirements-windows.txt" -ForegroundColor Gray
Write-Host "     pip install pyinstaller" -ForegroundColor Gray
Write-Host "     pyinstaller --name FreeKaraoke --onedir --windowed core\launcher.py" -ForegroundColor Gray
Write-Host ""
Write-Host "  4. Скопируйте модели из core/models/ в dist/FreeKaraoke/models/" -ForegroundColor DarkGray
Write-Host "  5. Скопируйте ffmpeg в dist/FreeKaraoke/" -ForegroundColor DarkGray
Write-Host "  6. Упакуйте dist/FreeKaraoke/ в ZIP" -ForegroundColor DarkGray
Write-Host ""

#!/usr/bin/env python3
"""
Кастомный файловый диалог на os.scandir() + PyQt6.
Не зависит от QFileDialog/QFileSystemModel — не виснет на сетевых монтированиях.
Работает офлайн на Linux, Windows, macOS.
"""
import os
import sys
import stat
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeView, QPushButton,
    QLabel, QLineEdit, QHeaderView, QAbstractItemView
)
from PyQt6.QtCore import Qt, QAbstractItemModel, QModelIndex, QFileInfo
from PyQt6.QtGui import QIcon


AUDIO_EXTENSIONS = {
    '.mp3', '.flac', '.m4a', '.wav', '.ogg', '.aac', '.alac', '.wma'
}


def _is_network_mount(path):
    """Быстрая проверка на сетевое монтирование. Не блокирует."""
    if sys.platform == 'linux':
        try:
            import subprocess
            result = subprocess.run(
                ['df', '-T', path], capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    fs_type = lines[-1].split()[-2]
                    return fs_type in ('nfs', 'nfs4', 'cifs', 'smbfs', 'fuse.sshfs')
        except Exception:
            pass
    return False


def _list_dir(path):
    """Быстрое перечисление директории через os.scandir(). Пропускает битые ссылки."""
    entries = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    # Пропускаем битые symbolic links
                    entry.is_dir()
                    entries.append(entry)
                except (PermissionError, OSError):
                    pass
    except (PermissionError, OSError):
        pass
    return entries


class DirEntry:
    """Обёртка над os.DirEntry для модели."""
    def __init__(self, name, path, is_dir, size=0):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.size = size


class FileModel(QAbstractItemModel):
    """Модель файловой системы на os.scandir(). Не использует QFileSystemModel."""

    COL_NAME = 0
    COL_SIZE = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = None
        self._entries = []
        self._columns = ['Имя', 'Размер']

    def set_root_path(self, path):
        """Установить корневую директорию."""
        self.beginResetModel()
        self._root = path
        self._load_entries()
        self.endResetModel()

    def _load_entries(self):
        if not self._root or not os.path.isdir(self._root):
            self._entries = []
            return

        entries = _list_dir(self._root)
        self._entries = []

        for e in entries:
            try:
                name = e.name
                # Скрытые файлы пропускаем
                if name.startswith('.'):
                    continue
                is_dir = e.is_dir(follow_symlinks=False)
                size = e.stat(follow_symlinks=False).st_size if not is_dir else 0
                self._entries.append(DirEntry(name, e.path, is_dir, size))
            except (PermissionError, OSError):
                pass

        # Сортировка: папки сверху, потом файлы, по алфавиту
        self._entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._entries)

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._entries):
            return None

        entry = self._entries[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == self.COL_NAME:
                return entry.name
            elif index.column() == self.COL_SIZE:
                if entry.is_dir:
                    return ''
                if entry.size >= 1024 * 1024:
                    return f'{entry.size / (1024*1024):.1f} MB'
                elif entry.size >= 1024:
                    return f'{entry.size / 1024:.1f} KB'
                return f'{entry.size} B'

        if role == Qt.ItemDataRole.FontRole:
            entry = self._entries[index.row()]
            if entry.is_dir:
                from PyQt6.QtGui import QFont
                font = QFont()
                font.setBold(True)
                return font

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._columns[section]
        return None

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        return self.createIndex(row, column)

    def parent(self, index):
        return QModelIndex()

    def is_dir(self, index):
        if not index.isValid():
            return False
        return self._entries[index.row()].is_dir

    def entry_path(self, index):
        if not index.isValid():
            return ''
        return self._entries[index.row()].path

    def entry_name(self, index):
        if not index.isValid():
            return ''
        return self._entries[index.row()].name

    def go_up(self):
        """Перейти на уровень вверх."""
        if self._root:
            parent = os.path.dirname(self._root)
            if parent and parent != self._root:
                self.set_root_path(parent)
                return True
        return False

    def current_path(self):
        return self._root or ''


class FileDialog(QDialog):
    """Кастомный диалог выбора файлов."""

    def __init__(self, parent=None, multiple=True, start_dir=None):
        super().__init__(parent)
        self._multiple = multiple
        self._selected_files = []

        self.setWindowTitle('Выберите аудиофайлы' if multiple else 'Выберите аудиофайл')
        self.resize(700, 500)

        # Layout
        layout = QVBoxLayout(self)

        # Путь
        path_layout = QHBoxLayout()
        self.path_label = QLabel('Путь:')
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        path_layout.addWidget(self.path_label)
        path_layout.addWidget(self.path_edit)
        layout.addLayout(path_layout)

        # Дерево файлов
        self.tree = QTreeView()
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
            if multiple else QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree)

        # Модель
        self.model = FileModel(self)
        self.tree.setModel(self.model)

        # Кнопки
        btn_layout = QHBoxLayout()

        self.up_btn = QPushButton('↑ Наверх')
        self.up_btn.clicked.connect(self._on_up)
        btn_layout.addWidget(self.up_btn)

        btn_layout.addStretch()

        self.ok_btn = QPushButton('Открыть')
        self.ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(self.ok_btn)

        self.cancel_btn = QPushButton('Отмена')
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

        # Стартовая директория
        if start_dir and os.path.isdir(start_dir):
            self.model.set_root_path(start_dir)
        else:
            self.model.set_root_path(os.path.expanduser('~'))

        self._update_path()

    def _update_path(self):
        self.path_edit.setText(self.model.current_path())

    def _on_double_click(self, index):
        if self.model.is_dir(index):
            path = self.model.entry_path(index)
            self.model.set_root_path(path)
            self._update_path()
        else:
            self._on_accept()

    def _on_up(self):
        if self.model.go_up():
            self._update_path()

    def _on_accept(self):
        selected = self.tree.selectedIndexes()
        if not selected:
            return

        files = []
        for idx in selected:
            if idx.column() == 0:  # Только колонка имени
                path = self.model.entry_path(idx)
                if not self.model.is_dir(idx):
                    files.append(path)

        if not files:
            return

        self._selected_files = files
        self.accept()

    def selected_files(self):
        return self._selected_files


def open_file_dialog(parent=None, multiple=True, start_dir=None):
    """Открыть кастомный файловый диалог. Возвращает список путей."""
    dialog = FileDialog(parent, multiple, start_dir)
    result = dialog.exec()
    if result == QDialog.DialogCode.Accepted:
        return dialog.selected_files()
    return []


if __name__ == '__main__':
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    files = open_file_dialog(multiple=True)
    print('Выбранные файлы:')
    for f in files:
        print(f'  {f}')

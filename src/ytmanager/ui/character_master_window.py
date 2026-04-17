from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ytmanager.character_master import CharacterMasterEntry, dump_character_master_entries
from ytmanager.master_builder import (
    DEFAULT_BUILD_SOURCES,
    MasterBuildResult,
    SourceBuildResult,
    build_quality_warnings,
    collect_sources_to_directory,
    merge_master_entries,
)
from ytmanager.paths import user_data_dir
from ytmanager.storage import AppDatabase, CharacterMasterRecord

RARITY_CHOICES = ("", "4", "5", "S", "A", "B")
MASTER_COLUMNS = ("게임", "한국명", "영문명", "표시명", "희귀도", "속성", "경로/역할", "별칭수")
ALIAS_COLUMNS = ("게임", "별칭", "정규명", "출처")


class MasterBuildWorker(QThread):
    progress = Signal(int, int)
    log = Signal(str)
    finished_result = Signal(object)

    def __init__(self, source_keys: tuple[str, ...], output_dir: Path, database_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source_keys = source_keys
        self.output_dir = output_dir
        self.database_path = database_path

    def run(self) -> None:
        try:
            total = len(self.source_keys)
            self.progress.emit(0, total)
            self.log.emit(f"소스 {total}개 수집을 시작합니다.")
            entries, results = self._collect_with_progress(total)
            self.log.emit(f"수집 완료: 총 {len(entries)}건 · 병합 시작")
            merged = merge_master_entries(entries)
            self.log.emit(f"병합 완료: {len(merged)}건")
            imported = self._apply_to_database(merged)
            warnings = build_quality_warnings(merged)
            for warning in warnings:
                self.log.emit(f"경고: {warning}")
            game_counts: dict[str, int] = {}
            source_counts: dict[str, int] = {}
            for entry in merged:
                game_counts[entry.game_key] = game_counts.get(entry.game_key, 0) + 1
                source_counts[entry.source_name] = source_counts.get(entry.source_name, 0) + 1
            result = MasterBuildResult(
                sources=tuple(results),
                merged_count=len(merged),
                merged_path=str(self.output_dir / "character_master.merged.json"),
                report_path="",
                imported_count=imported,
                source_counts=source_counts,
                game_counts=game_counts,
                quality_warnings=warnings,
            )
            self._write_merged_file(merged)
            self.progress.emit(total, total)
            self.finished_result.emit(result)
        except Exception as exc:  # Worker는 UI 크래시 없이 에러를 로그로 전달한다.
            self.log.emit(f"빌드 실패: {exc}")
            self.finished_result.emit(None)

    def _collect_with_progress(self, total: int) -> tuple[list[CharacterMasterEntry], list[SourceBuildResult]]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        all_entries: list[CharacterMasterEntry] = []
        results: list[SourceBuildResult] = []
        for index, source_key in enumerate(self.source_keys, start=1):
            self.log.emit(f"[{index}/{total}] {source_key} 수집 중…")
            try:
                entries, source_results = collect_sources_to_directory((source_key,), self.output_dir, continue_on_error=True)
                all_entries.extend(entries)
                results.extend(source_results)
                for result in source_results:
                    if result.ok:
                        self.log.emit(f"  → 성공 {result.count}건 · {result.output_path}")
                    else:
                        self.log.emit(f"  → 실패: {result.error}")
            except Exception as exc:
                self.log.emit(f"  → 예외: {exc}")
                results.append(SourceBuildResult(source_key=source_key, ok=False, error=str(exc)))
            self.progress.emit(index, total)
        return all_entries, results

    def _write_merged_file(self, entries: list[CharacterMasterEntry]) -> None:
        merged_path = self.output_dir / "character_master.merged.json"
        dump_character_master_entries(entries, merged_path)
        self.log.emit(f"병합 파일 저장: {merged_path}")

    def _apply_to_database(self, entries: list[CharacterMasterEntry]) -> int:
        db = AppDatabase(self.database_path)
        try:
            game_keys = {entry.game_key for entry in entries}
            db.clear_character_master_by_game(game_keys)
            for entry in entries:
                db.upsert_character_master(entry)
            return len(entries)
        finally:
            db.close()


class CharacterTableModel(QAbstractTableModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: list[CharacterMasterRecord] = []

    def set_records(self, records: list[CharacterMasterRecord]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()

    def record_at(self, row: int) -> Optional[CharacterMasterRecord]:
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(MASTER_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(MASTER_COLUMNS):
            return MASTER_COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        record = self._records[index.row()]
        column = index.column()
        if column == 0:
            return record.game_key
        if column == 1:
            return record.canonical_name_ko
        if column == 2:
            return record.canonical_name_en
        if column == 3:
            return record.display_name
        if column == 4:
            return record.rarity
        if column == 5:
            return record.element
        if column == 6:
            return record.role_or_path
        if column == 7:
            return len(record.aliases_ko)
        return None


class AliasTableModel(QAbstractTableModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, row: int) -> Optional[dict]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(ALIAS_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(ALIAS_COLUMNS):
            return ALIAS_COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self._rows[index.row()]
        column = index.column()
        if column == 0:
            return row.get("game_key", "")
        if column == 1:
            return row.get("alias", "")
        if column == 2:
            return row.get("canonical_name", "")
        if column == 3:
            return row.get("source", "")
        return None


class CharacterMasterWindow(QDialog):
    def __init__(self, db: AppDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("캐릭터 마스터 관리")
        self.resize(1100, 760)
        self._db = db
        self._worker: Optional[MasterBuildWorker] = None
        self._current_master_record: Optional[CharacterMasterRecord] = None

        self._build_ui()
        self._reload_master_table()
        self._reload_alias_table()

    # ---------- UI 구성 ----------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_tab_build(), "빌드")
        self.tabs.addTab(self._build_tab_master(), "캐릭터 목록")
        self.tabs.addTab(self._build_tab_alias(), "별칭 관리")

    def _build_tab_build(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        sources_group = QGroupBox("수집 소스")
        sources_layout = QVBoxLayout(sources_group)
        self.source_checkboxes: dict[str, QCheckBox] = {}
        for key in DEFAULT_BUILD_SOURCES:
            checkbox = QCheckBox(key)
            checkbox.setChecked(True)
            sources_layout.addWidget(checkbox)
            self.source_checkboxes[key] = checkbox
        select_row = QHBoxLayout()
        select_all_btn = QPushButton("전체 선택")
        select_all_btn.clicked.connect(self._select_all_sources)
        clear_all_btn = QPushButton("전체 해제")
        clear_all_btn.clicked.connect(self._clear_all_sources)
        select_row.addWidget(select_all_btn)
        select_row.addWidget(clear_all_btn)
        select_row.addStretch(1)
        sources_layout.addLayout(select_row)
        root.addWidget(sources_group)

        run_row = QHBoxLayout()
        self.run_build_btn = QPushButton("빌드 실행")
        self.run_build_btn.clicked.connect(self._start_build)
        run_row.addWidget(self.run_build_btn)
        run_row.addStretch(1)
        root.addLayout(run_row)

        self.build_progress = QProgressBar()
        self.build_progress.setRange(0, 1)
        self.build_progress.setValue(0)
        root.addWidget(self.build_progress)

        self.build_summary_label = QLabel("대기 중")
        self.build_summary_label.setWordWrap(True)
        root.addWidget(self.build_summary_label)

        root.addWidget(QLabel("빌드 로그"))
        self.build_log = QPlainTextEdit()
        self.build_log.setReadOnly(True)
        root.addWidget(self.build_log, stretch=1)

        return page

    def _build_tab_master(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("게임:"))
        self.master_game_combo = QComboBox()
        self.master_game_combo.addItem("(전체)", "")
        self.master_game_combo.currentIndexChanged.connect(self._reload_master_table)
        top_row.addWidget(self.master_game_combo)
        top_row.addWidget(QLabel("검색:"))
        self.master_search = QLineEdit()
        self.master_search.setPlaceholderText("한국명/영문명/별칭 검색")
        self.master_search.textChanged.connect(self._apply_master_filter)
        top_row.addWidget(self.master_search, stretch=1)
        self.master_add_btn = QPushButton("새 항목 추가")
        self.master_add_btn.clicked.connect(self._new_master_entry)
        top_row.addWidget(self.master_add_btn)
        self.master_delete_btn = QPushButton("삭제")
        self.master_delete_btn.clicked.connect(self._delete_master_entry)
        top_row.addWidget(self.master_delete_btn)
        root.addLayout(top_row)

        splitter = QSplitter(Qt.Vertical)
        root.addWidget(splitter, stretch=1)

        self.master_table = QTableView()
        self.master_model = CharacterTableModel(self)
        self.master_table.setModel(self.master_model)
        self.master_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.master_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.master_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.master_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.master_table.horizontalHeader().setStretchLastSection(True)
        self.master_table.clicked.connect(self._on_master_row_clicked)
        self.master_table.doubleClicked.connect(self._on_master_row_clicked)
        splitter.addWidget(self.master_table)

        editor = QGroupBox("편집")
        form = QFormLayout(editor)
        self.edit_game_key = QLineEdit()
        self.edit_canonical_ko = QLineEdit()
        self.edit_canonical_en = QLineEdit()
        self.edit_display_name = QLineEdit()
        self.edit_rarity = QComboBox()
        for value in RARITY_CHOICES:
            self.edit_rarity.addItem(value or "(없음)", value)
        self.edit_element = QLineEdit()
        self.edit_role = QLineEdit()
        self.edit_aliases = QLineEdit()
        self.edit_aliases.setPlaceholderText("쉼표로 구분")
        self.edit_extra = QTextEdit()
        self.edit_extra.setPlaceholderText('{"key": "value"}')
        self.edit_extra.setFixedHeight(80)
        form.addRow("게임 키", self.edit_game_key)
        form.addRow("한국 공식명", self.edit_canonical_ko)
        form.addRow("영문명", self.edit_canonical_en)
        form.addRow("표시명", self.edit_display_name)
        form.addRow("희귀도", self.edit_rarity)
        form.addRow("속성", self.edit_element)
        form.addRow("경로/역할", self.edit_role)
        form.addRow("별칭 목록", self.edit_aliases)
        form.addRow("메모/extra", self.edit_extra)
        button_row = QHBoxLayout()
        save_btn = QPushButton("저장")
        save_btn.clicked.connect(self._save_master_entry)
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self._clear_master_editor)
        button_row.addStretch(1)
        button_row.addWidget(save_btn)
        button_row.addWidget(cancel_btn)
        form.addRow(button_row)
        splitter.addWidget(editor)
        splitter.setSizes([440, 280])

        return page

    def _build_tab_alias(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("게임:"))
        self.alias_game_combo = QComboBox()
        self.alias_game_combo.addItem("(전체)", "")
        self.alias_game_combo.currentIndexChanged.connect(self._reload_alias_table)
        top_row.addWidget(self.alias_game_combo)
        top_row.addWidget(QLabel("검색:"))
        self.alias_search = QLineEdit()
        self.alias_search.setPlaceholderText("별칭/정규명 검색")
        self.alias_search.textChanged.connect(self._apply_alias_filter)
        top_row.addWidget(self.alias_search, stretch=1)
        root.addLayout(top_row)

        self.alias_table = QTableView()
        self.alias_model = AliasTableModel(self)
        self.alias_table.setModel(self.alias_model)
        self.alias_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.alias_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.alias_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.alias_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.alias_table.horizontalHeader().setStretchLastSection(True)
        self.alias_table.clicked.connect(self._on_alias_row_clicked)
        root.addWidget(self.alias_table, stretch=1)

        form_box = QGroupBox("별칭 추가/삭제")
        form_layout = QHBoxLayout(form_box)
        form_layout.addWidget(QLabel("별칭:"))
        self.alias_input = QLineEdit()
        self.alias_input.setPlaceholderText("새 별칭")
        form_layout.addWidget(self.alias_input, stretch=1)
        form_layout.addWidget(QLabel("정규명:"))
        self.alias_canonical_combo = QComboBox()
        self.alias_canonical_combo.setEditable(True)
        self.alias_canonical_combo.setMinimumWidth(180)
        form_layout.addWidget(self.alias_canonical_combo, stretch=1)
        add_btn = QPushButton("추가")
        add_btn.clicked.connect(self._add_alias)
        form_layout.addWidget(add_btn)
        delete_btn = QPushButton("삭제")
        delete_btn.clicked.connect(self._delete_alias)
        form_layout.addWidget(delete_btn)
        root.addWidget(form_box)

        io_row = QHBoxLayout()
        export_btn = QPushButton("JSON 내보내기")
        export_btn.clicked.connect(self._export_alias_json)
        import_btn = QPushButton("JSON 불러오기")
        import_btn.clicked.connect(self._import_alias_json)
        io_row.addWidget(export_btn)
        io_row.addWidget(import_btn)
        io_row.addStretch(1)
        root.addLayout(io_row)

        return page

    # ---------- 빌드 탭 ----------
    def _select_all_sources(self) -> None:
        for checkbox in self.source_checkboxes.values():
            checkbox.setChecked(True)

    def _clear_all_sources(self) -> None:
        for checkbox in self.source_checkboxes.values():
            checkbox.setChecked(False)

    def _start_build(self) -> None:
        selected = tuple(key for key, checkbox in self.source_checkboxes.items() if checkbox.isChecked())
        if not selected:
            QMessageBox.information(self, "소스 선택 필요", "최소 한 개 이상의 소스를 선택하세요.")
            return
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "빌드 진행 중", "현재 빌드가 진행 중입니다. 완료 후 다시 시도하세요.")
            return
        output_dir = user_data_dir() / "character_master_build"
        self.build_log.clear()
        self.build_summary_label.setText("빌드 진행 중…")
        self.build_progress.setRange(0, max(1, len(selected)))
        self.build_progress.setValue(0)
        self.run_build_btn.setEnabled(False)

        self._worker = MasterBuildWorker(selected, output_dir, self._db.path, self)
        self._worker.progress.connect(self._on_build_progress)
        self._worker.log.connect(self._on_build_log)
        self._worker.finished_result.connect(self._on_build_finished)
        self._worker.start()

    def _on_build_progress(self, current: int, total: int) -> None:
        self.build_progress.setRange(0, max(1, total))
        self.build_progress.setValue(current)

    def _on_build_log(self, message: str) -> None:
        self.build_log.appendPlainText(message)

    def _on_build_finished(self, result: object) -> None:
        self.run_build_btn.setEnabled(True)
        if not isinstance(result, MasterBuildResult):
            self.build_summary_label.setText("빌드 실패")
            self._worker = None
            return
        parts: list[str] = []
        parts.append(f"병합 {result.merged_count}건 · import {result.imported_count}건")
        if result.game_counts:
            game_parts = ", ".join(f"{key}={count}" for key, count in sorted(result.game_counts.items()))
            parts.append(f"게임별: {game_parts}")
        if result.quality_warnings:
            parts.append(f"품질 경고 {len(result.quality_warnings)}건")
        self.build_summary_label.setText(" · ".join(parts))
        self._reload_master_table()
        self._reload_alias_table()
        self._worker = None

    # ---------- 캐릭터 목록 탭 ----------
    def _reload_master_table(self) -> None:
        game_key = self.master_game_combo.currentData() if hasattr(self, "master_game_combo") else ""
        records = self._db.list_character_master(game_key or None)
        self._refresh_game_combos(records)
        self.master_model.set_records(records)
        self._apply_master_filter(self.master_search.text() if hasattr(self, "master_search") else "")
        self._refresh_alias_canonical_combo()

    def _refresh_game_combos(self, records: list[CharacterMasterRecord]) -> None:
        game_keys = sorted({record.game_key for record in records})
        for combo in (self.master_game_combo, self.alias_game_combo):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(전체)", "")
            for key in game_keys:
                combo.addItem(key, key)
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _apply_master_filter(self, text: str) -> None:
        keyword = (text or "").strip().casefold()
        for row in range(self.master_model.rowCount()):
            record = self.master_model.record_at(row)
            if not record:
                continue
            if not keyword:
                self.master_table.setRowHidden(row, False)
                continue
            haystack = " ".join([
                record.game_key,
                record.canonical_name_ko,
                record.canonical_name_en,
                record.display_name,
                record.rarity,
                record.element,
                record.role_or_path,
                " ".join(record.aliases_ko),
            ]).casefold()
            self.master_table.setRowHidden(row, keyword not in haystack)

    def _on_master_row_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        record = self.master_model.record_at(index.row())
        if record is None:
            return
        self._load_master_record_into_editor(record)

    def _load_master_record_into_editor(self, record: CharacterMasterRecord) -> None:
        self._current_master_record = record
        self.edit_game_key.setText(record.game_key)
        self.edit_canonical_ko.setText(record.canonical_name_ko)
        self.edit_canonical_en.setText(record.canonical_name_en)
        self.edit_display_name.setText(record.display_name)
        rarity_index = self.edit_rarity.findData(record.rarity)
        self.edit_rarity.setCurrentIndex(rarity_index if rarity_index >= 0 else 0)
        self.edit_element.setText(record.element)
        self.edit_role.setText(record.role_or_path)
        self.edit_aliases.setText(", ".join(record.aliases_ko))
        try:
            self.edit_extra.setPlainText(json.dumps(record.extra, ensure_ascii=False, indent=2) if record.extra else "")
        except (TypeError, ValueError):
            self.edit_extra.setPlainText("")

    def _clear_master_editor(self) -> None:
        self._current_master_record = None
        self.edit_game_key.clear()
        self.edit_canonical_ko.clear()
        self.edit_canonical_en.clear()
        self.edit_display_name.clear()
        self.edit_rarity.setCurrentIndex(0)
        self.edit_element.clear()
        self.edit_role.clear()
        self.edit_aliases.clear()
        self.edit_extra.clear()

    def _new_master_entry(self) -> None:
        self._clear_master_editor()
        self.edit_game_key.setFocus()

    def _save_master_entry(self) -> None:
        game_key = self.edit_game_key.text().strip()
        canonical_ko = self.edit_canonical_ko.text().strip()
        if not game_key or not canonical_ko:
            QMessageBox.warning(self, "필드 부족", "게임 키와 한국 공식명은 필수입니다.")
            return
        aliases = tuple(alias.strip() for alias in self.edit_aliases.text().split(",") if alias.strip())
        rarity = self.edit_rarity.currentData() or ""
        extra_text = self.edit_extra.toPlainText().strip()
        try:
            extra = json.loads(extra_text) if extra_text else {}
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "메모 파싱 실패", f"extra 필드는 유효한 JSON이어야 합니다.\n\n{exc}")
            return
        if not isinstance(extra, dict):
            QMessageBox.warning(self, "메모 형식 오류", "extra 필드는 JSON 객체여야 합니다.")
            return
        entry = CharacterMasterEntry(
            game_key=game_key,
            canonical_name_ko=canonical_ko,
            canonical_name_en=self.edit_canonical_en.text().strip(),
            display_name=self.edit_display_name.text().strip() or canonical_ko,
            aliases_ko=aliases,
            rarity=rarity,
            element=self.edit_element.text().strip(),
            role_or_path=self.edit_role.text().strip(),
            source_name="manual",
            source_url="",
            extra=extra,
        )
        try:
            self._db.upsert_character_master(entry)
        except Exception as exc:
            QMessageBox.critical(self, "저장 실패", f"캐릭터를 저장하지 못했습니다.\n\n{exc}")
            return
        self._reload_master_table()
        self._reload_alias_table()
        QMessageBox.information(self, "저장 완료", f"{canonical_ko} 저장을 완료했습니다.")

    def _delete_master_entry(self) -> None:
        record = self._current_master_record
        if record is None:
            selection = self.master_table.selectionModel().selectedRows() if self.master_table.selectionModel() else []
            if selection:
                record = self.master_model.record_at(selection[0].row())
        if record is None:
            QMessageBox.information(self, "대상 없음", "삭제할 캐릭터를 목록에서 선택하세요.")
            return
        answer = QMessageBox.question(
            self,
            "삭제 확인",
            f"'{record.game_key} / {record.canonical_name_ko}' 항목을 삭제합니다. 계속할까요?",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self._db.delete_character_master(record.game_key, record.canonical_name_ko)
        except Exception as exc:
            QMessageBox.critical(self, "삭제 실패", f"캐릭터 삭제 중 오류가 발생했습니다.\n\n{exc}")
            return
        self._clear_master_editor()
        self._reload_master_table()

    # ---------- 별칭 탭 ----------
    def _reload_alias_table(self) -> None:
        game_key = self.alias_game_combo.currentData() if hasattr(self, "alias_game_combo") else ""
        rows = self._db.list_aliases(game_key or None)
        self.alias_model.set_rows(rows)
        self._apply_alias_filter(self.alias_search.text() if hasattr(self, "alias_search") else "")
        self._refresh_alias_canonical_combo()

    def _apply_alias_filter(self, text: str) -> None:
        keyword = (text or "").strip().casefold()
        for row in range(self.alias_model.rowCount()):
            entry = self.alias_model.row_at(row)
            if not entry:
                continue
            if not keyword:
                self.alias_table.setRowHidden(row, False)
                continue
            haystack = " ".join(str(entry.get(key, "")) for key in ("game_key", "alias", "canonical_name", "source")).casefold()
            self.alias_table.setRowHidden(row, keyword not in haystack)

    def _refresh_alias_canonical_combo(self) -> None:
        if not hasattr(self, "alias_canonical_combo"):
            return
        current = self.alias_canonical_combo.currentText()
        game_key = self.alias_game_combo.currentData() if hasattr(self, "alias_game_combo") else ""
        records = self._db.list_character_master(game_key or None)
        self.alias_canonical_combo.blockSignals(True)
        self.alias_canonical_combo.clear()
        for record in records:
            label = record.canonical_name_ko
            if not game_key:
                label = f"{record.game_key} / {record.canonical_name_ko}"
            self.alias_canonical_combo.addItem(label, (record.game_key, record.canonical_name_ko))
        self.alias_canonical_combo.setEditText(current)
        self.alias_canonical_combo.blockSignals(False)

    def _on_alias_row_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        entry = self.alias_model.row_at(index.row())
        if not entry:
            return
        self.alias_input.setText(entry.get("alias", ""))
        canonical = entry.get("canonical_name", "")
        game_key = entry.get("game_key", "")
        combo_index = self.alias_canonical_combo.findData((game_key, canonical))
        if combo_index >= 0:
            self.alias_canonical_combo.setCurrentIndex(combo_index)
        else:
            self.alias_canonical_combo.setEditText(canonical)

    def _resolve_alias_target(self) -> tuple[str, str]:
        data = self.alias_canonical_combo.currentData()
        if isinstance(data, tuple) and len(data) == 2:
            return str(data[0]), str(data[1])
        game_key = self.alias_game_combo.currentData() or ""
        canonical = self.alias_canonical_combo.currentText().strip()
        return game_key, canonical

    def _add_alias(self) -> None:
        alias = self.alias_input.text().strip()
        game_key, canonical = self._resolve_alias_target()
        if not alias or not canonical or not game_key:
            QMessageBox.warning(self, "입력 부족", "게임 키, 별칭, 정규명이 모두 필요합니다.")
            return
        try:
            self._db.add_alias(game_key, alias, canonical, source="manual")
        except Exception as exc:
            QMessageBox.critical(self, "추가 실패", f"별칭 추가 중 오류가 발생했습니다.\n\n{exc}")
            return
        self.alias_input.clear()
        self._reload_alias_table()

    def _delete_alias(self) -> None:
        selection = self.alias_table.selectionModel().selectedRows() if self.alias_table.selectionModel() else []
        if not selection:
            QMessageBox.information(self, "대상 없음", "삭제할 별칭을 목록에서 선택하세요.")
            return
        entry = self.alias_model.row_at(selection[0].row())
        if not entry:
            return
        answer = QMessageBox.question(
            self,
            "삭제 확인",
            f"'{entry.get('game_key', '')} / {entry.get('alias', '')}' 별칭을 삭제합니다. 계속할까요?",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self._db.delete_alias(str(entry.get("game_key", "")), str(entry.get("alias", "")))
        except Exception as exc:
            QMessageBox.critical(self, "삭제 실패", f"별칭 삭제 중 오류가 발생했습니다.\n\n{exc}")
            return
        self._reload_alias_table()

    def _export_alias_json(self) -> None:
        default_dir = str(user_data_dir())
        path, _ = QFileDialog.getSaveFileName(self, "별칭 JSON 내보내기", f"{default_dir}/character_aliases.json", "JSON (*.json)")
        if not path:
            return
        rows = self._db.list_aliases(None)
        payload: dict[str, dict[str, list[str]]] = {}
        for row in rows:
            game_key = row.get("game_key", "")
            alias = row.get("alias", "")
            canonical = row.get("canonical_name", "")
            if not game_key or not canonical:
                continue
            aliases = payload.setdefault(game_key, {}).setdefault(canonical, [])
            if alias and alias != canonical and alias not in aliases:
                aliases.append(alias)
        try:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "내보내기 실패", f"파일 저장 중 오류가 발생했습니다.\n\n{exc}")
            return
        QMessageBox.information(self, "내보내기 완료", f"별칭 데이터를 저장했습니다.\n\n{path}")

    def _import_alias_json(self) -> None:
        default_dir = str(user_data_dir())
        path, _ = QFileDialog.getOpenFileName(self, "별칭 JSON 불러오기", default_dir, "JSON (*.json)")
        if not path:
            return
        try:
            count = self._db.load_character_aliases_from_file(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "불러오기 실패", f"파일 처리 중 오류가 발생했습니다.\n\n{exc}")
            return
        self._reload_alias_table()
        QMessageBox.information(self, "불러오기 완료", f"별칭 {count}개 그룹을 import 했습니다.")

    # ---------- 종료 처리 ----------
    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
        super().closeEvent(event)

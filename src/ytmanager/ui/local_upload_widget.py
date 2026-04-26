from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QSignalBlocker, QTimer, QUrl, Qt
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ytmanager.ffmpeg_tools import FFmpegToolchain, FFmpegToolsError, format_seconds, probe_local_video, resolve_ffmpeg_toolchain
from ytmanager.local_upload import (
    DEFAULT_PRIVACY_STATUS,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_PROCESSING,
    QUEUE_STATUS_UPLOADED,
    LocalUploadController,
    UploadQueueItem,
    build_segment_title,
    upload_local_video_segment,
)
from ytmanager.paths import user_cache_dir
from ytmanager.rules import RuleMapping, unique_tags
from ytmanager.timestamps import format_timestamp
from ytmanager.youtube_api import YouTubeApiClient
from ytmanager.ffmpeg_tools import split_video_segments


class LocalUploadWidget(QWidget):
    def __init__(
        self,
        *,
        rules: list[RuleMapping],
        settings_store,
        ensure_youtube_client: Callable[[], Optional[YouTubeApiClient]],
        status_message: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.rules = rules
        self.settings_store = settings_store
        self.ensure_youtube_client = ensure_youtube_client
        self.status_message = status_message
        self.controller = LocalUploadController(
            rules,
            settings_store,
            prober=probe_local_video,
            splitter=split_video_segments,
            uploader=upload_local_video_segment,
        )
        self.toolchain: FFmpegToolchain | None = None
        self._loading = False
        self._selected_segment_index: int | None = None

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.video_widget = QVideoWidget(self)
        self.player.setVideoOutput(self.video_widget)

        self._build_ui()
        self._connect_player_signals()
        self._refresh_session_labels()
        self._refresh_segment_editor_enabled(False)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        left = QWidget()
        left.setFixedWidth(320)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        session_group = QGroupBox("세션")
        session_layout = QVBoxLayout(session_group)
        self.file_label = QLabel("선택된 파일 없음")
        self.file_label.setWordWrap(True)
        self.source_info_label = QLabel("길이/해상도/날짜 정보 없음")
        self.source_info_label.setWordWrap(True)
        self.media_root_label = QLabel("기본 폴더: -")
        self.media_root_label.setWordWrap(True)
        session_buttons = QHBoxLayout()
        open_btn = QPushButton("파일 열기")
        open_btn.clicked.connect(self.open_media_file)
        pin_btn = QPushButton("루트 고정")
        pin_btn.clicked.connect(self.pin_media_root)
        clear_pin_btn = QPushButton("루트 해제")
        clear_pin_btn.clicked.connect(self.clear_media_root)
        session_buttons.addWidget(open_btn)
        session_buttons.addWidget(pin_btn)
        session_buttons.addWidget(clear_pin_btn)
        tool_buttons = QHBoxLayout()
        tool_status_btn = QPushButton("ffmpeg 확인")
        tool_status_btn.clicked.connect(self.check_ffmpeg_toolchain)
        add_cut_btn = QPushButton("현재 위치 컷 추가")
        add_cut_btn.clicked.connect(self.add_cut_from_current_position)
        tool_buttons.addWidget(tool_status_btn)
        tool_buttons.addWidget(add_cut_btn)
        session_layout.addWidget(self.file_label)
        session_layout.addWidget(self.source_info_label)
        session_layout.addWidget(self.media_root_label)
        session_layout.addLayout(session_buttons)
        session_layout.addLayout(tool_buttons)
        left_layout.addWidget(session_group)

        keyframe_group = QGroupBox("키프레임")
        keyframe_layout = QVBoxLayout(keyframe_group)
        self.keyframe_list = QListWidget()
        self.keyframe_list.itemDoubleClicked.connect(self._seek_to_keyframe_item)
        keyframe_actions = QHBoxLayout()
        add_selected_cut_btn = QPushButton("선택 컷 추가")
        add_selected_cut_btn.clicked.connect(self.add_cut_from_selected_keyframe)
        seek_selected_btn = QPushButton("선택 이동")
        seek_selected_btn.clicked.connect(self.seek_selected_keyframe)
        keyframe_actions.addWidget(add_selected_cut_btn)
        keyframe_actions.addWidget(seek_selected_btn)
        keyframe_layout.addWidget(self.keyframe_list, stretch=1)
        keyframe_layout.addLayout(keyframe_actions)
        left_layout.addWidget(keyframe_group, stretch=1)

        segment_group = QGroupBox("세그먼트")
        segment_layout = QVBoxLayout(segment_group)
        self.segment_list = QListWidget()
        self.segment_list.currentItemChanged.connect(self._on_segment_selected)
        segment_actions = QHBoxLayout()
        remove_cut_btn = QPushButton("선택 컷 삭제")
        remove_cut_btn.clicked.connect(self.remove_selected_cut)
        queue_btn = QPushButton("큐 갱신")
        queue_btn.clicked.connect(self.rebuild_queue)
        segment_actions.addWidget(remove_cut_btn)
        segment_actions.addWidget(queue_btn)
        segment_layout.addWidget(self.segment_list, stretch=1)
        segment_layout.addLayout(segment_actions)
        left_layout.addWidget(segment_group, stretch=1)

        queue_group = QGroupBox("업로드 큐")
        queue_layout = QVBoxLayout(queue_group)
        self.queue_list = QListWidget()
        upload_btn = QPushButton("큐 업로드 실행")
        upload_btn.clicked.connect(self.upload_queue)
        queue_layout.addWidget(self.queue_list, stretch=1)
        queue_layout.addWidget(upload_btn)
        left_layout.addWidget(queue_group, stretch=1)

        root.addWidget(left)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, stretch=1)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)
        player_title = QLabel("로컬 플레이어 (16:9)")
        center_layout.addWidget(player_title)
        self.video_widget.setAspectRatioMode(Qt.KeepAspectRatio)
        self.video_widget.setFixedSize(720, 405)
        center_layout.addWidget(self.video_widget, alignment=Qt.AlignLeft | Qt.AlignTop)
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self._seek_slider_position)
        center_layout.addWidget(self.position_slider)
        player_controls = QHBoxLayout()
        back_btn = QPushButton("-5초")
        back_btn.clicked.connect(lambda: self.seek_relative(-5000))
        play_btn = QPushButton("재생/정지")
        play_btn.clicked.connect(self.toggle_playback)
        forward_btn = QPushButton("+5초")
        forward_btn.clicked.connect(lambda: self.seek_relative(5000))
        self.position_label = QLabel("00:00 / --:--")
        player_controls.addWidget(back_btn)
        player_controls.addWidget(play_btn)
        player_controls.addWidget(forward_btn)
        player_controls.addWidget(self.position_label)
        player_controls.addStretch(1)
        center_layout.addLayout(player_controls)
        splitter.addWidget(center)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        common_group = QGroupBox("공통 메타데이터")
        common_layout = QFormLayout(common_group)
        self.game_combo = QComboBox()
        for rule in self.rules:
            label = f"{rule.display_name or rule.title_prefix} [{rule.title_prefix}]"
            self.game_combo.addItem(label, rule.title_prefix)
        self.game_combo.currentIndexChanged.connect(self._on_common_game_changed)
        self.title_input = QLineEdit()
        self.title_input.textChanged.connect(self._refresh_title_preview_only)
        self.date_input = QLineEdit()
        self.date_input.textChanged.connect(self._refresh_title_preview_only)
        self.title_preview_label = QLabel("-")
        self.title_preview_label.setWordWrap(True)
        self.tags_input = QLineEdit()
        self.description_input = QPlainTextEdit()
        self.description_input.setPlaceholderText("세그먼트 공통 설명 초안")
        self.privacy_combo = QComboBox()
        for value, label in (("private", "비공개"), ("unlisted", "일부 공개"), ("public", "공개")):
            self.privacy_combo.addItem(label, value)
        apply_common_btn = QPushButton("공통 초안 세그먼트에 복제")
        apply_common_btn.clicked.connect(self.apply_common_metadata_to_segments)
        common_layout.addRow("게임", self.game_combo)
        common_layout.addRow("제목", self.title_input)
        common_layout.addRow("날짜", self.date_input)
        common_layout.addRow("제목 프리뷰", self.title_preview_label)
        common_layout.addRow("상단 태그", self.tags_input)
        common_layout.addRow("설명", self.description_input)
        common_layout.addRow("공개범위", self.privacy_combo)
        common_layout.addRow("", apply_common_btn)
        right_layout.addWidget(common_group)

        segment_meta_group = QGroupBox("선택 세그먼트")
        segment_meta_layout = QFormLayout(segment_meta_group)
        self.keep_checkbox = QCheckBox("업로드 유지")
        self.keep_checkbox.stateChanged.connect(self._save_selected_segment)
        self.segment_title_input = QLineEdit()
        self.segment_title_input.textChanged.connect(self._save_selected_segment)
        self.segment_tags_input = QLineEdit()
        self.segment_tags_input.textChanged.connect(self._save_selected_segment)
        self.segment_description_input = QPlainTextEdit()
        self.segment_description_input.textChanged.connect(self._save_selected_segment)
        self.segment_privacy_combo = QComboBox()
        for value, label in (("private", "비공개"), ("unlisted", "일부 공개"), ("public", "공개")):
            self.segment_privacy_combo.addItem(label, value)
        self.segment_privacy_combo.currentIndexChanged.connect(self._save_selected_segment)
        segment_meta_layout.addRow("유지", self.keep_checkbox)
        segment_meta_layout.addRow("제목", self.segment_title_input)
        segment_meta_layout.addRow("태그", self.segment_tags_input)
        segment_meta_layout.addRow("설명", self.segment_description_input)
        segment_meta_layout.addRow("공개범위", self.segment_privacy_combo)
        right_layout.addWidget(segment_meta_group, stretch=1)
        right_layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([760, 420])

    def _connect_player_signals(self) -> None:
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)

    def _refresh_session_labels(self) -> None:
        self.media_root_label.setText(f"기본 폴더: {self.controller.media_root()}")
        session = self.controller.session
        if session is None:
            self.file_label.setText("선택된 파일 없음")
            self.source_info_label.setText("길이/해상도/날짜 정보 없음")
            self.title_preview_label.setText("-")
            return
        probe = session.probe
        self.file_label.setText(str(session.source_path))
        created = probe.created_at or "-"
        self.source_info_label.setText(
            f"길이 {format_timestamp(probe.duration_seconds)} · {probe.width_pixels}×{probe.height_pixels} · 날짜 {created}"
        )
        self.title_preview_label.setText(session.title_preview or "-")

    def _ensure_toolchain(self) -> FFmpegToolchain:
        if self.toolchain is None:
            self.toolchain = resolve_ffmpeg_toolchain(allow_download=True)
            self.settings_store.set_setting("ffmpeg_version", self.toolchain.version)
            self.settings_store.set_setting("ffmpeg_bin_path", str(self.toolchain.ffmpeg_path))
            self.settings_store.set_setting("ffprobe_bin_path", str(self.toolchain.ffprobe_path))
        return self.toolchain

    def check_ffmpeg_toolchain(self) -> None:
        try:
            toolchain = self._ensure_toolchain()
        except Exception as exc:
            QMessageBox.warning(self, "ffmpeg 준비 실패", str(exc))
            return
        source = "자동 캐시" if toolchain.managed else "시스템 설치"
        QMessageBox.information(
            self,
            "ffmpeg 준비 완료",
            f"출처: {source}\n버전: {toolchain.version}\nffmpeg: {toolchain.ffmpeg_path}\nffprobe: {toolchain.ffprobe_path}",
        )
        self.status_message(f"ffmpeg 준비 완료: {toolchain.version}")

    def pin_media_root(self) -> None:
        start_dir = str(self.controller.media_root())
        selected = QFileDialog.getExistingDirectory(self, "고정 미디어 루트 선택", start_dir)
        if not selected:
            return
        self.controller.set_pinned_media_root(selected)
        self._refresh_session_labels()
        self.status_message(f"고정 미디어 루트를 저장했습니다: {selected}")

    def clear_media_root(self) -> None:
        self.controller.clear_pinned_media_root()
        self._refresh_session_labels()
        self.status_message("고정 미디어 루트를 해제했습니다.")

    def open_media_file(self) -> None:
        start_dir = str(self.controller.media_root())
        path, _ = QFileDialog.getOpenFileName(self, "로컬 영상 선택", start_dir, "Video Files (*.mkv *.mp4)")
        if not path:
            return
        self.load_media_file(Path(path))

    def load_media_file(self, path: Path) -> None:
        try:
            toolchain = self._ensure_toolchain()
            session = self.controller.load_source(path, ffprobe_path=toolchain.ffprobe_path)
        except Exception as exc:
            QMessageBox.warning(self, "영상 로드 실패", str(exc))
            return
        self._loading = True
        try:
            self.player.setSource(QUrl.fromLocalFile(str(session.source_path)))
            self.player.pause()
            self._populate_common_fields_from_session(session)
            self._populate_keyframes()
            self._populate_segments()
            self.rebuild_queue()
            self._refresh_session_labels()
        finally:
            self._loading = False
        self.status_message(f"로컬 영상 로드 완료: {path.name}")

    def _populate_common_fields_from_session(self, session) -> None:
        with QSignalBlocker(self.game_combo):
            for index in range(self.game_combo.count()):
                if self.game_combo.itemData(index) == session.game_title_prefix:
                    self.game_combo.setCurrentIndex(index)
                    break
        self.title_input.setText(session.title_text)
        self.date_input.setText(session.date_text)
        self.tags_input.setText(" ".join(session.tags))
        self.description_input.setPlainText(session.description)
        self._set_combo_data(self.privacy_combo, session.privacy_status or DEFAULT_PRIVACY_STATUS)
        self._refresh_title_preview_only()

    def _populate_keyframes(self) -> None:
        self.keyframe_list.clear()
        session = self.controller.session
        if session is None:
            return
        for seconds in session.probe.keyframes:
            item = QListWidgetItem(f"{format_timestamp(seconds)} · {seconds:.3f}s")
            item.setData(Qt.UserRole, float(seconds))
            self.keyframe_list.addItem(item)

    def _populate_segments(self) -> None:
        self.segment_list.clear()
        session = self.controller.session
        if session is None:
            return
        for segment in session.segments:
            prefix = "KEEP" if segment.keep else "SKIP"
            item = QListWidgetItem(
                f"{segment.index:02d}. [{prefix}] {format_timestamp(segment.start_seconds)} ~ {format_timestamp(segment.end_seconds)}\n{segment.title}"
            )
            item.setData(Qt.UserRole, segment.index)
            self.segment_list.addItem(item)
        if session.segments:
            self.segment_list.setCurrentRow(0)

    def _populate_queue(self) -> None:
        self.queue_list.clear()
        for item in self.controller.queue:
            label = {
                QUEUE_STATUS_PENDING: "대기",
                QUEUE_STATUS_PROCESSING: "처리 중",
                QUEUE_STATUS_UPLOADED: "완료",
                QUEUE_STATUS_FAILED: "실패",
            }.get(item.status, item.status)
            line = f"[{label}] {item.segment.title}"
            if item.error_message:
                line = f"{line}\n{item.error_message}"
            self.queue_list.addItem(line)

    def _refresh_title_preview_only(self) -> None:
        session = self.controller.session
        prefix = self.game_combo.currentData() if self.game_combo.count() else ""
        preview = build_segment_title(prefix or "", self.title_input.text(), self.date_input.text())
        self.title_preview_label.setText(preview or "-")
        if session is None:
            return
        session.game_title_prefix = prefix or ""
        session.title_text = self.title_input.text().strip()
        session.date_text = self.date_input.text().strip()
        session.description = self.description_input.toPlainText()
        session.tags = unique_tags(self.tags_input.text().split())
        session.privacy_status = str(self.privacy_combo.currentData() or DEFAULT_PRIVACY_STATUS)

    def _on_common_game_changed(self) -> None:
        if self.controller.session is None:
            return
        prefix = str(self.game_combo.currentData() or "")
        rule = next((rule for rule in self.rules if rule.title_prefix == prefix), None)
        if rule is not None:
            self.tags_input.setText(" ".join(rule.description_tags))
        self._refresh_title_preview_only()

    def apply_common_metadata_to_segments(self) -> None:
        if self.controller.session is None:
            QMessageBox.information(self, "세션 필요", "먼저 로컬 영상을 선택하세요.")
            return
        self.controller.update_common_metadata(
            game_title_prefix=str(self.game_combo.currentData() or ""),
            title_text=self.title_input.text(),
            date_text=self.date_input.text(),
            description=self.description_input.toPlainText(),
            tags=self.tags_input.text().split(),
            privacy_status=str(self.privacy_combo.currentData() or DEFAULT_PRIVACY_STATUS),
        )
        self.controller.overwrite_segment_defaults()
        self._populate_segments()
        self.rebuild_queue()
        self.status_message("공통 메타데이터를 세그먼트 초안에 복제했습니다.")

    def add_cut_from_selected_keyframe(self) -> None:
        item = self.keyframe_list.currentItem()
        if item is None:
            return
        self._add_cut_seconds(float(item.data(Qt.UserRole) or 0.0))

    def seek_selected_keyframe(self) -> None:
        item = self.keyframe_list.currentItem()
        if item is None:
            return
        self.player.setPosition(int(float(item.data(Qt.UserRole) or 0.0) * 1000))

    def _seek_to_keyframe_item(self, item: QListWidgetItem) -> None:
        self.player.setPosition(int(float(item.data(Qt.UserRole) or 0.0) * 1000))

    def add_cut_from_current_position(self) -> None:
        session = self.controller.session
        if session is None:
            return
        current = self.player.position() / 1000
        if session.probe.keyframes:
            nearest = min(session.probe.keyframes, key=lambda value: abs(value - current))
        else:
            nearest = current
        self._add_cut_seconds(nearest)

    def _add_cut_seconds(self, seconds: float) -> None:
        try:
            self.controller.add_cut(seconds)
        except Exception as exc:
            QMessageBox.warning(self, "컷 추가 실패", str(exc))
            return
        self._populate_segments()
        self.rebuild_queue()
        self.status_message(f"컷포인트 추가: {format_timestamp(seconds)}")

    def remove_selected_cut(self) -> None:
        item = self.segment_list.currentItem()
        session = self.controller.session
        if item is None or session is None:
            return
        index = int(item.data(Qt.UserRole) or 0)
        if index <= 1 or index - 2 >= len(session.cuts):
            QMessageBox.information(self, "컷 선택 필요", "삭제할 컷에 대응하는 뒤쪽 세그먼트를 선택하세요.")
            return
        cut_seconds = session.cuts[index - 2].seconds
        self.controller.remove_cut(cut_seconds)
        self._populate_segments()
        self.rebuild_queue()
        self.status_message(f"컷포인트 삭제: {format_timestamp(cut_seconds)}")

    def rebuild_queue(self) -> None:
        if self.controller.session is None:
            self.queue_list.clear()
            return
        self.controller.build_queue()
        self._populate_queue()

    def _on_segment_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if current is None:
            self._selected_segment_index = None
            self._refresh_segment_editor_enabled(False)
            return
        index = int(current.data(Qt.UserRole) or 0)
        self._selected_segment_index = index
        segment = self.controller.require_segment(index)
        self._loading = True
        try:
            self.keep_checkbox.setChecked(segment.keep)
            self.segment_title_input.setText(segment.title)
            self.segment_tags_input.setText(" ".join(segment.tags))
            self.segment_description_input.setPlainText(segment.description)
            self._set_combo_data(self.segment_privacy_combo, segment.privacy_status)
        finally:
            self._loading = False
        self._refresh_segment_editor_enabled(True)

    def _refresh_segment_editor_enabled(self, enabled: bool) -> None:
        for widget in (
            self.keep_checkbox,
            self.segment_title_input,
            self.segment_tags_input,
            self.segment_description_input,
            self.segment_privacy_combo,
        ):
            widget.setEnabled(enabled)

    def _save_selected_segment(self) -> None:
        if self._loading or self._selected_segment_index is None:
            return
        self.controller.update_segment(
            self._selected_segment_index,
            keep=self.keep_checkbox.isChecked(),
            title=self.segment_title_input.text(),
            tags=self.segment_tags_input.text().split(),
            description=self.segment_description_input.toPlainText(),
            privacy_status=str(self.segment_privacy_combo.currentData() or DEFAULT_PRIVACY_STATUS),
        )
        self._populate_segments()
        self.rebuild_queue()

    def upload_queue(self) -> None:
        if self.controller.session is None:
            QMessageBox.information(self, "세션 필요", "먼저 로컬 영상을 선택하세요.")
            return
        if not self.controller.queue:
            self.rebuild_queue()
        if not self.controller.queue:
            QMessageBox.information(self, "업로드 대상 없음", "keep 상태의 세그먼트가 없습니다.")
            return
        youtube = self.ensure_youtube_client()
        if youtube is None:
            return
        try:
            toolchain = self._ensure_toolchain()
        except Exception as exc:
            QMessageBox.warning(self, "ffmpeg 준비 실패", str(exc))
            return
        session = self.controller.require_session()
        output_dir = user_cache_dir() / "local-upload-segments" / session.source_path.stem
        try:
            self.status_message("세그먼트 분할 및 업로드를 시작합니다...")
            summary = self.controller.process_queue(youtube, ffmpeg_path=toolchain.ffmpeg_path, output_dir=output_dir)
        except Exception as exc:
            QMessageBox.critical(self, "업로드 실패", str(exc))
            return
        self._populate_queue()
        QMessageBox.information(
            self,
            "업로드 완료",
            f"성공 {summary.succeeded}개 / 실패 {summary.failed}개 / 전체 {summary.total}개",
        )
        self.status_message(f"로컬 세그먼트 업로드 완료: 성공 {summary.succeeded}, 실패 {summary.failed}")

    def toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek_relative(self, delta_ms: int) -> None:
        self.player.setPosition(max(0, self.player.position() + delta_ms))

    def _seek_slider_position(self, value: int) -> None:
        self.player.setPosition(value)

    def _on_position_changed(self, value: int) -> None:
        with QSignalBlocker(self.position_slider):
            self.position_slider.setValue(value)
        self._refresh_position_label(value, self.player.duration())

    def _on_duration_changed(self, value: int) -> None:
        self.position_slider.setRange(0, max(0, value))
        self._refresh_position_label(self.player.position(), value)

    def _refresh_position_label(self, current_ms: int, duration_ms: int) -> None:
        self.position_label.setText(f"{format_timestamp(current_ms / 1000)} / {format_timestamp(duration_ms / 1000) if duration_ms > 0 else '--:--'}")

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

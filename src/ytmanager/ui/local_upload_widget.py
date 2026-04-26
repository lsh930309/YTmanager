from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QSignalBlocker, QSize, QTimer, QUrl, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
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

from ytmanager.ffmpeg_tools import (
    FFmpegToolchain,
    FFmpegToolsError,
    capture_video_frame,
    probe_local_video,
    resolve_ffmpeg_toolchain,
    split_video_segments,
)
from ytmanager.local_upload import (
    DEFAULT_PRIVACY_STATUS,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_PROCESSING,
    QUEUE_STATUS_UPLOADED,
    LocalUploadController,
    LocalVideoProbe,
    build_segment_title,
    upload_local_video_segment,
)
from ytmanager.paths import user_cache_dir
from ytmanager.rules import RuleMapping, unique_tags
from ytmanager.timestamps import format_timestamp
from ytmanager.youtube_api import YouTubeApiClient

CARD_THUMB_WIDTH = 160
CARD_THUMB_HEIGHT = 90
AUTOSAVE_DEBOUNCE_MS = 400


class AspectRatioVideoFrame(QWidget):
    def __init__(self, child: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.child = child
        self.child.setParent(self)
        self.setMinimumWidth(480)
        self.setMinimumHeight(270)

    def hasHeightForWidth(self) -> bool:  # type: ignore[override]
        return True

    def heightForWidth(self, width: int) -> int:  # type: ignore[override]
        return max(180, int(width * 9 / 16))

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(960, 540)

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(480, 270)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.child.setGeometry(self.rect())


class SegmentCardWidget(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("segmentCard")
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.thumbnail_label = QLabel("썸네일 없음")
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setFixedSize(CARD_THUMB_WIDTH, CARD_THUMB_HEIGHT)
        self.thumbnail_label.setStyleSheet("background:#111;border:1px solid #333;color:#aaa;")
        layout.addWidget(self.thumbnail_label, alignment=Qt.AlignCenter)

        self.status_label = QLabel()
        self.time_label = QLabel()
        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumWidth(CARD_THUMB_WIDTH)
        self.title_label.setStyleSheet("font-weight:600;")
        layout.addWidget(self.status_label)
        layout.addWidget(self.time_label)
        layout.addWidget(self.title_label)
        self._set_frame_style(False, False, True)

    def update_card(self, segment, *, active: bool, selected: bool) -> None:
        status = "KEEP" if segment.keep else "SKIP"
        self.status_label.setText(f"{segment.index:02d}. [{status}]")
        self.time_label.setText(f"{format_timestamp(segment.start_seconds)} ~ {format_timestamp(segment.end_seconds)}")
        self.title_label.setText(segment.title or "제목 없음")
        thumb_path = Path(segment.thumbnail_path) if segment.thumbnail_path else None
        if thumb_path and thumb_path.exists():
            pixmap = QPixmap(str(thumb_path))
            if not pixmap.isNull():
                preview = pixmap.scaled(CARD_THUMB_WIDTH, CARD_THUMB_HEIGHT, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                self.thumbnail_label.setPixmap(preview)
                self.thumbnail_label.setText("")
            else:
                self.thumbnail_label.setPixmap(QPixmap())
                self.thumbnail_label.setText("썸네일 오류")
        else:
            self.thumbnail_label.setPixmap(QPixmap())
            self.thumbnail_label.setText("썸네일 없음")
        self._set_frame_style(active, selected, segment.keep)

    def _set_frame_style(self, active: bool, selected: bool, keep: bool) -> None:
        border = "#1565c0" if selected else ("#2e7d32" if active else "#333")
        background = "#121c28" if selected else ("#171f17" if active else "#1b1b1b")
        text = "#ddd" if keep else "#999"
        self.setStyleSheet(
            f"QFrame#segmentCard{{background:{background};border:2px solid {border};border-radius:8px;color:{text};}}"
        )


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
        self._active_segment_index: int | None = None
        self._scrub_resume_playback = False
        self._slider_dragging = False
        self.restored_session_loaded = False

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.video_widget = QVideoWidget(self)
        self.player.setVideoOutput(self.video_widget)
        self.video_frame = AspectRatioVideoFrame(self.video_widget, self)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(AUTOSAVE_DEBOUNCE_MS)
        self.autosave_timer.timeout.connect(lambda: self.save_session_now(silent=True))

        self._build_ui()
        self._connect_player_signals()
        self._refresh_session_labels()
        self._refresh_segment_editor_enabled(False)
        self._restore_autosave_session()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        left = QWidget()
        left.setFixedWidth(320)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        session_group = QGroupBox("세션 정보")
        session_layout = QVBoxLayout(session_group)
        self.file_label = QLabel("선택된 파일 없음")
        self.file_label.setWordWrap(True)
        self.source_info_label = QLabel("길이/해상도/날짜 정보 없음")
        self.source_info_label.setWordWrap(True)
        self.media_root_label = QLabel("기본 폴더: -")
        self.media_root_label.setWordWrap(True)
        self.autosave_label = QLabel("임시 저장 없음")
        self.autosave_label.setWordWrap(True)
        button_row1 = QHBoxLayout()
        open_btn = QPushButton("파일 열기")
        open_btn.clicked.connect(self.open_media_file)
        pin_btn = QPushButton("루트 고정")
        pin_btn.clicked.connect(self.pin_media_root)
        clear_pin_btn = QPushButton("루트 해제")
        clear_pin_btn.clicked.connect(self.clear_media_root)
        button_row1.addWidget(open_btn)
        button_row1.addWidget(pin_btn)
        button_row1.addWidget(clear_pin_btn)
        button_row2 = QHBoxLayout()
        ffmpeg_btn = QPushButton("ffmpeg 확인")
        ffmpeg_btn.clicked.connect(self.check_ffmpeg_toolchain)
        save_session_btn = QPushButton("세션 저장")
        save_session_btn.clicked.connect(self.save_session_now)
        button_row2.addWidget(ffmpeg_btn)
        button_row2.addWidget(save_session_btn)
        session_layout.addWidget(self.file_label)
        session_layout.addWidget(self.source_info_label)
        session_layout.addWidget(self.media_root_label)
        session_layout.addWidget(self.autosave_label)
        session_layout.addLayout(button_row1)
        session_layout.addLayout(button_row2)
        left_layout.addWidget(session_group)

        queue_group = QGroupBox("업로드 큐")
        queue_layout = QVBoxLayout(queue_group)
        self.queue_list = QListWidget()
        self.queue_list.setWordWrap(True)
        upload_btn = QPushButton("큐 업로드 실행")
        upload_btn.clicked.connect(self.upload_queue)
        queue_layout.addWidget(self.queue_list, stretch=1)
        queue_layout.addWidget(upload_btn)
        left_layout.addWidget(queue_group, stretch=1)
        root.addWidget(left)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        root.addWidget(content, stretch=1)

        top_splitter = QSplitter(Qt.Horizontal)
        content_layout.addWidget(top_splitter, stretch=3)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)
        center_layout.addWidget(QLabel("로컬 플레이어"))
        center_layout.addWidget(self.video_frame, 0, Qt.AlignTop)

        controls_row = QHBoxLayout()
        self.prev_keyframe_btn = QPushButton("⏮")
        self.prev_keyframe_btn.setToolTip("이전 키프레임 (←)")
        self.prev_keyframe_btn.clicked.connect(self.seek_prev_keyframe)
        self.prev_frame_btn = QPushButton("◂")
        self.prev_frame_btn.setToolTip("1프레임 뒤로 (,)")
        self.prev_frame_btn.clicked.connect(lambda: self.step_frame(-1))
        self.play_btn = QPushButton("⏵")
        self.play_btn.setToolTip("재생/일시정지 (Space)")
        self.play_btn.clicked.connect(self.toggle_playback)
        self.next_frame_btn = QPushButton("▸")
        self.next_frame_btn.setToolTip("1프레임 앞으로 (.)")
        self.next_frame_btn.clicked.connect(lambda: self.step_frame(1))
        self.next_keyframe_btn = QPushButton("⏭")
        self.next_keyframe_btn.setToolTip("다음 키프레임 (→)")
        self.next_keyframe_btn.clicked.connect(self.seek_next_keyframe)
        self.capture_thumb_btn = QPushButton("📸")
        self.capture_thumb_btn.setToolTip("선택 세그먼트 대표 썸네일 캡처 (Ctrl+P)")
        self.capture_thumb_btn.clicked.connect(self.capture_current_thumbnail)
        self.position_label = QLabel("00:00 / --:--")
        for button in (
            self.prev_keyframe_btn,
            self.prev_frame_btn,
            self.play_btn,
            self.next_frame_btn,
            self.next_keyframe_btn,
            self.capture_thumb_btn,
        ):
            button.setFixedHeight(32)
            controls_row.addWidget(button)
        controls_row.addWidget(self.position_label)
        controls_row.addStretch(1)
        center_layout.addLayout(controls_row)

        timeline_row = QHBoxLayout()
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderMoved.connect(self._seek_slider_position)
        self.position_slider.sliderReleased.connect(self._on_slider_released)
        self.insert_cut_btn = QPushButton("✂")
        self.insert_cut_btn.setToolTip("현재 위치에 컷 삽입")
        self.insert_cut_btn.clicked.connect(self.add_cut_from_current_position)
        timeline_row.addWidget(self.position_slider, stretch=1)
        timeline_row.addWidget(self.insert_cut_btn)
        center_layout.addLayout(timeline_row)
        center_layout.addStretch(1)
        top_splitter.addWidget(center)

        right = QWidget()
        right.setMinimumWidth(380)
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
        self.tags_input.textChanged.connect(self._refresh_title_preview_only)
        self.description_input = QPlainTextEdit()
        self.description_input.setPlaceholderText("세그먼트 공통 설명 초안")
        self.description_input.textChanged.connect(self._refresh_title_preview_only)
        self.privacy_combo = QComboBox()
        for value, label in (("private", "비공개"), ("unlisted", "일부 공개"), ("public", "공개")):
            self.privacy_combo.addItem(label, value)
        self.privacy_combo.currentIndexChanged.connect(self._refresh_title_preview_only)
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
        self.selected_segment_summary = QLabel("선택된 세그먼트 없음")
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
        segment_meta_layout.addRow("요약", self.selected_segment_summary)
        segment_meta_layout.addRow("유지", self.keep_checkbox)
        segment_meta_layout.addRow("제목", self.segment_title_input)
        segment_meta_layout.addRow("태그", self.segment_tags_input)
        segment_meta_layout.addRow("설명", self.segment_description_input)
        segment_meta_layout.addRow("공개범위", self.segment_privacy_combo)
        right_layout.addWidget(segment_meta_group, stretch=1)
        top_splitter.addWidget(right)
        top_splitter.setSizes([980, 420])

        bottom_group = QGroupBox("세그먼트 / 썸네일")
        bottom_layout = QVBoxLayout(bottom_group)
        bottom_header = QHBoxLayout()
        self.segment_panel_summary = QLabel("세그먼트 없음")
        remove_cut_btn = QPushButton("선택 컷 삭제")
        remove_cut_btn.clicked.connect(self.remove_selected_cut)
        bottom_header.addWidget(self.segment_panel_summary)
        bottom_header.addStretch(1)
        bottom_header.addWidget(remove_cut_btn)
        bottom_layout.addLayout(bottom_header)

        self.segment_card_list = QListWidget()
        self.segment_card_list.setSelectionMode(QListWidget.SingleSelection)
        self.segment_card_list.setViewMode(QListView.IconMode)
        self.segment_card_list.setFlow(QListView.LeftToRight)
        self.segment_card_list.setWrapping(True)
        self.segment_card_list.setResizeMode(QListView.Adjust)
        self.segment_card_list.setMovement(QListView.Static)
        self.segment_card_list.setSpacing(8)
        self.segment_card_list.currentItemChanged.connect(self._on_segment_selected)
        bottom_layout.addWidget(self.segment_card_list, stretch=1)
        content_layout.addWidget(bottom_group, stretch=2)

    def _connect_player_signals(self) -> None:
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)

    def has_active_session(self) -> bool:
        return self.controller.session is not None

    def _restore_autosave_session(self) -> None:
        restored = self.controller.restore_autosave()
        if restored is None:
            return
        session, selected_index, current_position_ms = restored
        self._loading = True
        try:
            self.player.setSource(QUrl.fromLocalFile(str(session.source_path)))
            self.player.pause()
            self._populate_common_fields_from_session(session)
            self._refresh_session_labels()
            self._refresh_segment_cards(selected_index=selected_index)
            self._populate_queue()
            if selected_index is not None:
                self._select_segment(selected_index)
            elif session.segments:
                self._select_segment(1)
            if current_position_ms is not None:
                self.player.setPosition(current_position_ms)
        finally:
            self._loading = False
        self.restored_session_loaded = True
        self._mark_saved("이전 로컬 편집 세션을 복원했습니다.")

    def _refresh_session_labels(self) -> None:
        self.media_root_label.setText(f"기본 폴더: {self.controller.media_root()}")
        session = self.controller.session
        if session is None:
            self.file_label.setText("선택된 파일 없음")
            self.source_info_label.setText("길이/해상도/날짜 정보 없음")
            self.title_preview_label.setText("-")
            self.segment_panel_summary.setText("세그먼트 없음")
            return
        probe = session.probe
        created = probe.created_at or "-"
        self.file_label.setText(str(session.source_path))
        self.source_info_label.setText(
            f"길이 {format_timestamp(probe.duration_seconds)} · {probe.width_pixels}×{probe.height_pixels} · {probe.effective_frame_rate():.2f}fps · 날짜 {created}"
        )
        self.title_preview_label.setText(session.title_preview or "-")
        self.segment_panel_summary.setText(f"세그먼트 {len(session.segments)}개 · keep {sum(1 for segment in session.segments if segment.keep)}개")

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
            self.player.setPosition(0)
            self._selected_segment_index = None
            self._active_segment_index = None
            self._populate_common_fields_from_session(session)
            self._refresh_session_labels()
            self._refresh_segment_cards(selected_index=1)
            self._populate_queue()
            self._select_segment(1)
        finally:
            self._loading = False
        self.save_session_now(silent=True)
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
        self._refresh_title_preview_only(schedule_autosave=False)

    def _refresh_segment_cards(self, *, selected_index: int | None = None) -> None:
        self.segment_card_list.clear()
        session = self.controller.session
        if session is None:
            return
        current_index = selected_index if selected_index is not None else self._selected_segment_index
        for segment in session.segments:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, segment.index)
            item.setSizeHint(QSize(CARD_THUMB_WIDTH + 24, 188))
            widget = SegmentCardWidget(self.segment_card_list)
            widget.update_card(segment, active=segment.index == self._active_segment_index, selected=segment.index == current_index)
            self.segment_card_list.addItem(item)
            self.segment_card_list.setItemWidget(item, widget)
        if current_index is not None:
            self._select_segment(current_index)
        self._update_segment_card_styles()

    def _update_segment_card_styles(self) -> None:
        session = self.controller.session
        if session is None:
            return
        for row in range(self.segment_card_list.count()):
            item = self.segment_card_list.item(row)
            index = int(item.data(Qt.UserRole) or 0)
            widget = self.segment_card_list.itemWidget(item)
            if not isinstance(widget, SegmentCardWidget):
                continue
            segment = self.controller.require_segment(index)
            widget.update_card(
                segment,
                active=index == self._active_segment_index,
                selected=index == self._selected_segment_index,
            )

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

    def _refresh_title_preview_only(self, schedule_autosave: bool = True) -> None:
        session = self.controller.session
        prefix = self.game_combo.currentData() if self.game_combo.count() else ""
        preview = build_segment_title(prefix or "", self.title_input.text(), self.date_input.text())
        self.title_preview_label.setText(preview or "-")
        if session is None:
            return
        session.game_title_prefix = str(prefix or "")
        session.title_text = self.title_input.text().strip()
        session.date_text = self.date_input.text().strip()
        session.description = self.description_input.toPlainText()
        session.tags = unique_tags(self.tags_input.text().split())
        session.privacy_status = str(self.privacy_combo.currentData() or DEFAULT_PRIVACY_STATUS)
        if schedule_autosave and not self._loading:
            self._schedule_autosave()

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
        self._after_session_mutation("공통 메타데이터를 세그먼트 초안에 복제했습니다.")

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
        active_index = self.controller.active_segment_index(seconds) or self._selected_segment_index or 1
        self._after_session_mutation(f"컷포인트 추가: {format_timestamp(seconds)}", select_index=active_index)

    def remove_selected_cut(self) -> None:
        session = self.controller.session
        index = self._selected_segment_index
        if index is None or session is None:
            return
        if index <= 1 or index - 2 >= len(session.cuts):
            QMessageBox.information(self, "컷 선택 필요", "삭제할 컷에 대응하는 뒤쪽 세그먼트를 선택하세요.")
            return
        cut_seconds = session.cuts[index - 2].seconds
        self.controller.remove_cut(cut_seconds)
        next_index = min(index - 1, len(self.controller.require_session().segments))
        self._after_session_mutation(f"컷포인트 삭제: {format_timestamp(cut_seconds)}", select_index=max(1, next_index))

    def _on_segment_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if current is None:
            self._selected_segment_index = None
            self.selected_segment_summary.setText("선택된 세그먼트 없음")
            self._refresh_segment_editor_enabled(False)
            self._update_segment_card_styles()
            return
        index = int(current.data(Qt.UserRole) or 0)
        self._selected_segment_index = index
        segment = self.controller.require_segment(index)
        self._loading = True
        try:
            self.selected_segment_summary.setText(
                f"{index:02d}. {format_timestamp(segment.start_seconds)} ~ {format_timestamp(segment.end_seconds)}"
            )
            self.keep_checkbox.setChecked(segment.keep)
            self.segment_title_input.setText(segment.title)
            self.segment_tags_input.setText(" ".join(segment.tags))
            self.segment_description_input.setPlainText(segment.description)
            self._set_combo_data(self.segment_privacy_combo, segment.privacy_status)
        finally:
            self._loading = False
        self._refresh_segment_editor_enabled(True)
        self._update_segment_card_styles()

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
        self._after_session_mutation(select_index=self._selected_segment_index)

    def _after_session_mutation(self, message: str | None = None, *, select_index: int | None = None) -> None:
        self.controller.build_queue()
        self._refresh_session_labels()
        self._refresh_segment_cards(selected_index=select_index)
        self._populate_queue()
        self._schedule_autosave()
        if message:
            self.status_message(message)

    def _schedule_autosave(self) -> None:
        if self._loading or self.controller.session is None:
            return
        self.autosave_timer.start()

    def _mark_saved(self, message: str | None = None) -> None:
        now_text = datetime.now().strftime("%H:%M:%S")
        self.autosave_label.setText(f"임시 저장됨: {now_text}")
        if message:
            self.status_message(message)

    def save_session_now(self, silent: bool = False) -> None:
        if self.controller.session is None:
            return
        self.controller.save_autosave(self._selected_segment_index, self.player.position())
        self._mark_saved(None if silent else "현재 로컬 편집 세션을 임시 저장했습니다.")

    def persist_session_on_close(self) -> None:
        self.save_session_now(silent=True)

    def clear_saved_session(self) -> None:
        self.controller.clear_autosave()
        self.autosave_label.setText("임시 저장 없음")

    def upload_queue(self) -> None:
        if self.controller.session is None:
            QMessageBox.information(self, "세션 필요", "먼저 로컬 영상을 선택하세요.")
            return
        if not self.controller.queue:
            self.controller.build_queue()
            self._populate_queue()
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
        if summary.failed == 0 and summary.total > 0:
            self.clear_saved_session()
        else:
            self.save_session_now(silent=True)
        QMessageBox.information(self, "업로드 완료", f"성공 {summary.succeeded}개 / 실패 {summary.failed}개 / 전체 {summary.total}개")
        self.status_message(f"로컬 세그먼트 업로드 완료: 성공 {summary.succeeded}, 실패 {summary.failed}")

    def toggle_playback(self) -> None:
        if self.controller.session is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek_prev_keyframe(self) -> None:
        if self.controller.session is None:
            return
        seconds = self.controller.keyframe_step_seconds(self.player.position() / 1000, -1)
        self.player.setPosition(int(seconds * 1000))

    def seek_next_keyframe(self) -> None:
        if self.controller.session is None:
            return
        seconds = self.controller.keyframe_step_seconds(self.player.position() / 1000, 1)
        self.player.setPosition(int(seconds * 1000))

    def step_frame(self, direction: int) -> None:
        session = self.controller.session
        if session is None:
            return
        self.player.pause()
        delta_ms = int(round(1000 / session.probe.effective_frame_rate()))
        self.player.setPosition(max(0, self.player.position() + direction * delta_ms))

    def capture_current_thumbnail(self) -> None:
        session = self.controller.session
        if session is None:
            QMessageBox.information(self, "세션 필요", "먼저 로컬 영상을 선택하세요.")
            return
        index = self._selected_segment_index or self.controller.active_segment_index(self.player.position() / 1000) or 1
        try:
            toolchain = self._ensure_toolchain()
            output_dir = user_cache_dir() / "local-upload-thumbnails" / session.source_path.stem
            output_path = output_dir / f"segment-{index:02d}.jpg"
            capture_video_frame(
                session.source_path,
                output_path,
                self.player.position() / 1000,
                toolchain.ffmpeg_path,
            )
            self.controller.set_segment_thumbnail(index, output_path)
        except Exception as exc:
            QMessageBox.warning(self, "썸네일 캡처 실패", str(exc))
            return
        self._after_session_mutation("선택 세그먼트 대표 썸네일을 저장했습니다.", select_index=index)

    def _on_slider_pressed(self) -> None:
        self._slider_dragging = True
        self._scrub_resume_playback = self.player.playbackState() == QMediaPlayer.PlayingState
        if self._scrub_resume_playback:
            self.player.pause()

    def _seek_slider_position(self, value: int) -> None:
        self.player.setPosition(value)
        self._refresh_position_label(value, self.player.duration())

    def _on_slider_released(self) -> None:
        self._slider_dragging = False
        self.player.setPosition(self.position_slider.value())
        if self._scrub_resume_playback:
            self.player.play()
        self._scrub_resume_playback = False

    def _on_position_changed(self, value: int) -> None:
        if not self._slider_dragging:
            with QSignalBlocker(self.position_slider):
                self.position_slider.setValue(value)
        self._refresh_position_label(value, self.player.duration())
        self._active_segment_index = self.controller.active_segment_index(value / 1000) if self.controller.session else None
        self._update_segment_card_styles()

    def _on_duration_changed(self, value: int) -> None:
        self.position_slider.setRange(0, max(0, value))
        self._refresh_position_label(self.player.position(), value)

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_btn.setText("⏸" if state == QMediaPlayer.PlayingState else "⏵")

    def _refresh_position_label(self, current_ms: int, duration_ms: int) -> None:
        self.position_label.setText(
            f"{format_timestamp(current_ms / 1000)} / {format_timestamp(duration_ms / 1000) if duration_ms > 0 else '--:--'}"
        )

    def _select_segment(self, index: int) -> None:
        for row in range(self.segment_card_list.count()):
            item = self.segment_card_list.item(row)
            if int(item.data(Qt.UserRole) or 0) == index:
                self.segment_card_list.setCurrentItem(item)
                return

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

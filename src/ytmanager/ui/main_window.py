from __future__ import annotations

import difflib
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QEasingCurve, QEvent, QThread, QTimer, QUrl, Qt, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCompleter,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from ytmanager.description import (
    DescriptionSection,
    PartyMember,
    extract_placeholders,
    load_template,
    load_template_library,
    render_description_template,
    select_template,
)
from ytmanager.ui.character_master_window import CharacterMasterWindow
from ytmanager.ui.local_upload_widget import LocalUploadWidget
from ytmanager.character_status import game_key_from_title_prefix, parse_party_status, format_party_status
from ytmanager.migration import build_migration_candidates, build_normalized_description, candidate_to_draft_record, is_managed_title
from ytmanager.models import TimestampEntry, VideoDraft, VideoSummary
from ytmanager.oauth import OAuthManager, OAuthSetupError
from ytmanager.paths import user_cache_dir, user_data_dir
from ytmanager.rules import extract_title_prefix, load_rule_mappings
from ytmanager.storage import (
    DRAFT_STATUS_APPLIED,
    DRAFT_STATUS_DRAFT,
    DRAFT_STATUS_ERROR,
    DRAFT_STATUS_REVIEWED,
    DRAFT_STATUS_SKIPPED,
    DescriptionDraftRecord,
    AppDatabase,
    utc_now_iso,
)
from ytmanager.thumbnail import public_thumbnail_url, public_watch_url, validate_thumbnail_file
from ytmanager.thumbnail_upscale import UpscaleResult, prepare_waifu2x_binary, upscale_thumbnail_candidate, waifu2x_status
from ytmanager.timestamps import format_timestamp, parse_timestamp
from ytmanager.youtube_api import YouTubeApiClient, YouTubeApiError

PLAYER_WIDTH = 640
PLAYER_HEIGHT = 360
THUMBNAIL_MODE_PLAYER_WIDTH = 1280
THUMBNAIL_MODE_PLAYER_HEIGHT = 720
THUMBNAIL_PREVIEW_WIDTH = 256
THUMBNAIL_PREVIEW_HEIGHT = 144
THUMBNAIL_EXPORT_WIDTH = 2560
THUMBNAIL_EXPORT_HEIGHT = 1440
THUMBNAIL_UPSCALE_MODE = "waifu2x"
THUMBNAIL_KEEP_UPSCALED_PNG = False
DEFAULT_FRAME_STEP_FPS = 30
KEYBOARD_SEEK_SECONDS = 5
BLACK_BORDER_THRESHOLD = 18
BLACK_BORDER_MIN_CROP_PX = 3
MODE_ANIMATION_MS = 180
SECTION_COLUMNS = ["stage_number", "boss_name", "party_composition", "party"]
FIELD_EXCLUDES = {
    "[tags]",
    "[timestamps]",
    "[timestamp]",
    "top_tags",
    "timestamps",
    "stage_number",
    "boss_name",
    "party_composition",
}
STATUS_LABELS = {
    DRAFT_STATUS_DRAFT: "초안",
    DRAFT_STATUS_REVIEWED: "검수 완료",
    DRAFT_STATUS_APPLIED: "적용 완료",
    DRAFT_STATUS_ERROR: "오류",
}

PLAYER_HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <style>
    html, body { margin: 0; width: 100%; height: 100%; background: #111; overflow: hidden; color: #eee; font-family: sans-serif; }
    #player { width: 100%; height: 100%; }
    #empty { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; color: #aaa; }
    iframe { display: block; background: #000; }
  </style>
</head>
<body>
  <div id="player"><div id="empty">영상을 선택하면 여기에 재생 화면이 표시됩니다.</div></div>
  <script>
    var player = null;
    var pendingVideoId = null;
    function loadApi() {
      var tag = document.createElement('script');
      tag.src = "https://www.youtube.com/iframe_api";
      var firstScriptTag = document.getElementsByTagName('script')[0];
      firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);
    }
    function onYouTubeIframeAPIReady() {
      if (pendingVideoId) { loadVideo(pendingVideoId); }
    }
    function onPlayerReady(event) {
      if (event && event.target && event.target.pauseVideo) { event.target.pauseVideo(); }
    }
    function loadVideo(videoId) {
      pendingVideoId = videoId;
      if (!window.YT || !window.YT.Player) { return; }
      if (player) {
        if (player.cueVideoById) { player.cueVideoById(videoId); }
        else { player.loadVideoById(videoId); player.pauseVideo(); }
      } else {
        player = new YT.Player('player', {
          width: '100%',
          height: '100%',
          videoId: videoId,
          playerVars: {
            'playsinline': 1,
            'origin': window.location.origin,
            'controls': 0,
            'disablekb': 1,
            'fs': 0,
            'iv_load_policy': 3,
            'rel': 0
          },
          events: {
            'onReady': onPlayerReady
          }
        });
      }
    }
    function getCurrentTimeSafe() {
      if (!player || !player.getCurrentTime) { return 0; }
      return player.getCurrentTime();
    }
    function getDurationSafe() {
      if (!player || !player.getDuration) { return 0; }
      return player.getDuration();
    }
    function getPlayerSnapshotSafe() {
      return {
        currentTime: getCurrentTimeSafe(),
        duration: getDurationSafe(),
        state: (player && player.getPlayerState) ? player.getPlayerState() : 0
      };
    }
    function seekToSafe(seconds) {
      if (player && player.seekTo) { player.seekTo(seconds, true); }
    }
    function seekRelative(delta) {
      if (!player || !player.getCurrentTime || !player.seekTo) { return 0; }
      var current = Number(player.getCurrentTime()) || 0;
      var next = Math.max(0, current + (Number(delta) || 0));
      player.seekTo(next, true);
      return next;
    }
    function stepFrame(direction, fps) {
      if (!player || !player.getCurrentTime || !player.seekTo) { return 0; }
      if (player.pauseVideo) { player.pauseVideo(); }
      var frameRate = Math.max(1, Number(fps) || 30);
      var current = Number(player.getCurrentTime()) || 0;
      var next = Math.max(0, current + (Number(direction) || 0) / frameRate);
      player.seekTo(next, true);
      return next;
    }
    function togglePlayPause() {
      if (!player || !player.getPlayerState) { return; }
      if (player.getPlayerState() === 1) {
        player.pauseVideo();
        return;
      }
      if (pendingVideoId && player.getPlayerState && player.getPlayerState() === 5 && player.loadVideoById) {
        player.loadVideoById(pendingVideoId);
      }
      if (player.playVideo) { player.playVideo(); }
    }
    loadApi();
  </script>
</body>
</html>
"""


class MouseShield(QWidget):
    """투명 마우스 차단막: YouTube iframe hover/click overlay 발생을 막는다."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.setFocus()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        event.accept()

    def enterEvent(self, event) -> None:  # type: ignore[override]
        event.accept()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        event.accept()


class FixedVideoFrame(QWidget):
    """여백 없이 고정 16:9 크기로 재생기를 담는 컨테이너."""

    def __init__(self, child: QWidget, width: int = PLAYER_WIDTH, height: int = PLAYER_HEIGHT) -> None:
        super().__init__()
        self.child = child
        self.child.setParent(self)
        self.mouse_shield = MouseShield(self)
        self.setFixedSize(width, height)
        self.child.setFixedSize(width, height)
        self.child.setGeometry(0, 0, width, height)
        self.mouse_shield.setGeometry(0, 0, width, height)
        self.mouse_shield.raise_()
        self.child.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background-color: #111;")

    def set_video_size(self, width: int, height: int) -> None:
        self.setFixedSize(width, height)
        self.child.setFixedSize(width, height)
        self.child.setGeometry(0, 0, width, height)
        self.mouse_shield.setGeometry(0, 0, width, height)
        self.mouse_shield.raise_()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.child.setGeometry(self.contentsRect())
        self.mouse_shield.setGeometry(self.contentsRect())
        self.mouse_shield.raise_()


class ThumbnailPreviewDialog(QDialog):
    """썸네일 후보를 크게 보여주는 클릭-닫기 뷰어."""

    def __init__(self, image_path: Optional[Path], fallback_pixmap: Optional[QPixmap], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("썸네일 후보 미리보기")
        self.setStyleSheet("background-color: #050505; color: #ddd;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        pixmap = QPixmap(str(image_path)) if image_path and image_path.exists() else QPixmap()
        if pixmap.isNull() and fallback_pixmap is not None:
            pixmap = QPixmap(fallback_pixmap)
        if not pixmap.isNull():
            pixmap.setDevicePixelRatio(1.0)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #050505;")
        self.image_label.installEventFilter(self)
        layout.addWidget(self.image_label)

        hint = QLabel("클릭 또는 Esc로 닫기")
        hint.setAlignment(Qt.AlignCenter)
        hint.installEventFilter(self)
        layout.addWidget(hint)

        self._set_display_pixmap(pixmap)

    def _set_display_pixmap(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            self.image_label.setText("표시할 썸네일 후보가 없습니다.")
            self.resize(480, 240)
            return
        available = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        max_width = max(320, int(available.width() * 0.82))
        max_height = max(240, int(available.height() * 0.82) - 48)
        scale = min(max_width / pixmap.width(), max_height / pixmap.height(), 2.0)
        scale = max(0.1, scale)
        display = pixmap.scaled(
            max(1, int(pixmap.width() * scale)),
            max(1, int(pixmap.height() * scale)),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        display.setDevicePixelRatio(1.0)
        self.image_label.setPixmap(display)
        self.resize(display.width() + 24, display.height() + 64)

    def eventFilter(self, watched: object, event: object) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.MouseButtonPress:  # type: ignore[attr-defined]
            self.close()
            return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        event.accept()
        self.close()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key_Escape:
            event.accept()
            self.close()
            return
        super().keyPressEvent(event)


class ThumbnailPreviewLabel(QLabel):
    """클릭하면 현재 썸네일 후보를 크게 여는 QLabel."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.candidate_path: Optional[Path] = None
        self.candidate_pixmap: Optional[QPixmap] = None
        self.viewer: Optional[ThumbnailPreviewDialog] = None
        self.setToolTip("캡처한 썸네일 후보가 없습니다.")

    def set_candidate(self, path: Path, pixmap: QPixmap) -> None:
        self.candidate_path = path
        self.candidate_pixmap = QPixmap(pixmap)
        self.setToolTip("클릭하면 크게 보기")
        self.setCursor(Qt.PointingHandCursor)

    def clear_candidate(self) -> None:
        self.candidate_path = None
        self.candidate_pixmap = None
        self.viewer = None
        self.unsetCursor()
        self.setToolTip("캡처한 썸네일 후보가 없습니다.")

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.candidate_path or self.candidate_pixmap:
            event.accept()
            self.viewer = ThumbnailPreviewDialog(self.candidate_path, self.candidate_pixmap, self.window())
            self.viewer.show()
            self.viewer.raise_()
            self.viewer.activateWindow()
            return
        super().mousePressEvent(event)


class ThumbnailUpscaleWorker(QThread):
    finished_result = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        input_path: Path,
        output_path: Path,
        mode: str = THUMBNAIL_UPSCALE_MODE,
        keep_upscaled_png: bool = THUMBNAIL_KEEP_UPSCALED_PNG,
    ) -> None:
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.mode = mode
        self.keep_upscaled_png = keep_upscaled_png

    def run(self) -> None:  # type: ignore[override]
        try:
            result = upscale_thumbnail_candidate(
                self.input_path,
                self.output_path,
                mode=self.mode,
                keep_upscaled_png=self.keep_upscaled_png,
            )
            self.finished_result.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class Waifu2xInstallWorker(QThread):
    finished_result = Signal(object)
    failed = Signal(str)

    def run(self) -> None:  # type: ignore[override]
        try:
            executable = prepare_waifu2x_binary()
            self.finished_result.emit(executable)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("YTmanager - YouTube 영상 관리")
        self.resize(1660, 960)
        self.setMinimumSize(1500, 860)
        self.db = AppDatabase()
        self._load_character_alias_files()
        self.oauth = OAuthManager()
        self.youtube: Optional[YouTubeApiClient] = None
        self.current_video: Optional[VideoSummary] = None
        self.current_draft: Optional[VideoDraft] = None
        self.current_description_draft: Optional[DescriptionDraftRecord] = None
        self.last_thumbnail_candidate: Optional[Path] = None
        self.thumbnail_upscale_worker: Optional[ThumbnailUpscaleWorker] = None
        self.waifu2x_install_worker: Optional[Waifu2xInstallWorker] = None
        self.template_text = load_template()
        self.template_library = load_template_library(self.template_text)
        self.rule_mappings = load_rule_mappings()
        self.field_edits: dict[str, QLineEdit] = {}
        self.template_buttons: dict[str, QRadioButton] = {}
        self._player_shortcuts: list[QShortcut] = []
        self._player_duration = 0.0
        self._thumbnail_mode = False
        self._mode_animation: Optional[QVariantAnimation] = None
        self._player_size_animation: Optional[QVariantAnimation] = None
        self._loading_ui = False
        self._character_master_window: Optional[CharacterMasterWindow] = None

        self._build_ui()
        self._install_player_shortcuts()
        self._player_time_timer = QTimer(self)
        self._player_time_timer.setInterval(500)
        self._player_time_timer.timeout.connect(self._refresh_player_time)
        self._player_time_timer.start()
        self._restore_google_session_if_available()
        self._load_cached_videos()

    def set_thumbnail_mode(self, enabled: bool) -> None:
        self._thumbnail_mode = enabled
        self.mode_toggle_btn.setText("ThumbNail" if enabled else "MetaData")
        self.mode_toggle_btn.setToolTip(
            "ThumbNail 모드: 재생기와 썸네일 후보를 크게 표시합니다."
            if enabled
            else "MetaData 모드: 설명/태그/타임스탬프 편집을 표시합니다."
        )
        self._animate_workspace_mode(enabled)

    def _animate_workspace_mode(self, thumbnail_mode: bool) -> None:
        total = max(1, sum(self.main_splitter.sizes()))
        start_sizes = self.main_splitter.sizes()
        target_sizes = [max(total - 8, int(total * 0.995)), 8] if thumbnail_mode else [760, 580]
        target_width = THUMBNAIL_MODE_PLAYER_WIDTH if thumbnail_mode else PLAYER_WIDTH
        target_height = THUMBNAIL_MODE_PLAYER_HEIGHT if thumbnail_mode else PLAYER_HEIGHT
        start_width = self.player_frame.width()
        start_height = self.player_frame.height()

        self.timestamp_panel.setVisible(not thumbnail_mode)
        self.right_panel.setVisible(True)

        self._mode_animation = QVariantAnimation(self)
        self._mode_animation.setDuration(MODE_ANIMATION_MS)
        self._mode_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._mode_animation.setStartValue(0.0)
        self._mode_animation.setEndValue(1.0)

        def update_splitter(progress: float) -> None:
            progress = float(progress)
            sizes = [
                int(start_sizes[0] + (target_sizes[0] - start_sizes[0]) * progress),
                int(start_sizes[1] + (target_sizes[1] - start_sizes[1]) * progress),
            ]
            self.main_splitter.setSizes(sizes)

        def finish_splitter() -> None:
            self.main_splitter.setSizes(target_sizes)
            self.right_panel.setVisible(not thumbnail_mode)
            self.timestamp_panel.setVisible(not thumbnail_mode)
            self.thumbnail_group.setVisible(thumbnail_mode)

        self._mode_animation.valueChanged.connect(update_splitter)
        self._mode_animation.finished.connect(finish_splitter)

        self._player_size_animation = QVariantAnimation(self)
        self._player_size_animation.setDuration(MODE_ANIMATION_MS)
        self._player_size_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._player_size_animation.setStartValue(0.0)
        self._player_size_animation.setEndValue(1.0)

        def update_player(progress: float) -> None:
            progress = float(progress)
            width = int(start_width + (target_width - start_width) * progress)
            height = int(start_height + (target_height - start_height) * progress)
            self.player_frame.set_video_size(width, height)
            self.player_title.setText(f"재생기 · {'썸네일 집중' if thumbnail_mode else '고정 16:9'} ({width}×{height})")

        def finish_player() -> None:
            self.player_frame.set_video_size(target_width, target_height)
            self.player_title.setText(
                f"재생기 · {'썸네일 집중' if thumbnail_mode else '고정 16:9'} ({target_width}×{target_height})"
            )

        self._player_size_animation.valueChanged.connect(update_player)
        self._player_size_animation.finished.connect(finish_player)
        self._mode_animation.start()
        self._player_size_animation.start()

    def _load_character_alias_files(self) -> None:
        for alias_path in (Path.cwd() / "character_aliases.json", user_data_dir() / "character_aliases.json"):
            self.db.load_character_aliases_from_file(alias_path)

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)
        self.setCentralWidget(root)

        workspace_row = QHBoxLayout()
        workspace_row.addWidget(QLabel("작업 공간"))
        self.metadata_workspace_btn = QRadioButton("YouTube 메타데이터")
        self.local_workspace_btn = QRadioButton("로컬 편집")
        self.metadata_workspace_btn.setChecked(True)
        self.metadata_workspace_btn.toggled.connect(lambda checked: self._set_workspace(0, checked))
        self.local_workspace_btn.toggled.connect(lambda checked: self._set_workspace(1, checked))
        workspace_row.addWidget(self.metadata_workspace_btn)
        workspace_row.addWidget(self.local_workspace_btn)
        workspace_row.addStretch(1)
        root_layout.addLayout(workspace_row)

        self.workspace_stack = QStackedWidget()
        root_layout.addWidget(self.workspace_stack, stretch=1)

        self.metadata_workspace = QWidget()
        metadata_layout = QHBoxLayout(self.metadata_workspace)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setSpacing(8)

        # --- 왼쪽: 영상 목록 (단일 줄 + 아이콘 상태) ---
        left = QWidget()
        left.setFixedWidth(300)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(QLabel("업로드 영상"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("제목 검색")
        self.search.textChanged.connect(self._filter_video_list)
        left_layout.addWidget(self.search)
        self.video_list = QListWidget()
        self.video_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.video_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.video_list.setWordWrap(False)
        self.video_list.setUniformItemSizes(True)
        self.video_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.video_list.currentItemChanged.connect(self._on_video_selected)
        left_layout.addWidget(self.video_list, stretch=1)

        # --- 사이드바 액션 버튼 ---
        _SIDE_BTN_SS = (
            "QPushButton{text-align:left;padding:5px 8px;"
            "border:none;border-radius:4px;color:#ccc;background:transparent;}"
            "QPushButton:hover{background:#2a2a2a;}"
            "QPushButton:pressed{background:#3a3a3a;}"
        )
        side_sep = QFrame()
        side_sep.setFrameShape(QFrame.HLine)
        side_sep.setStyleSheet("color:#444;")
        left_layout.addWidget(side_sep)
        for _label, _slot in [
            ("🔑  Google 로그인",       self.login),
            ("🔄  영상 목록 동기화",     self.sync_videos),
            ("📝  정규화 초안 생성",     self.generate_drafts_for_cached_videos),
            ("🚀  검수 완료 일괄 적용",  self.apply_reviewed_drafts),
            ("📚  캐릭터 마스터 관리",   self.open_character_master_window),
        ]:
            _b = QPushButton(_label)
            _b.setStyleSheet(_SIDE_BTN_SS)
            _b.clicked.connect(_slot)
            left_layout.addWidget(_b)
        self.mode_toggle_btn = QPushButton("MetaData")
        self.mode_toggle_btn.setCheckable(True)
        self.mode_toggle_btn.setToolTip("MetaData / ThumbNail 작업 모드 전환")
        self.mode_toggle_btn.toggled.connect(self.set_thumbnail_mode)
        self.mode_toggle_btn.setStyleSheet(
            "QPushButton{padding:5px 8px;border-radius:4px;"
            "background:#333;color:#ccc;border:none;text-align:left;}"
            "QPushButton:checked{background:#1565c0;color:white;font-weight:bold;}"
        )
        left_layout.addWidget(self.mode_toggle_btn)
        metadata_layout.addWidget(left)

        self.main_splitter = QSplitter(Qt.Horizontal)
        metadata_layout.addWidget(self.main_splitter, stretch=1)

        # --- 중앙: 재생기 + 타임스탬프 ---
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(6)

        self.player_panel = QWidget()
        player_layout = QVBoxLayout(self.player_panel)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.setSpacing(8)
        self.player_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.player_title = QLabel(f"재생기 · 고정 16:9 ({PLAYER_WIDTH}×{PLAYER_HEIGHT})")
        player_layout.addWidget(self.player_title)
        self.player = QWebEngineView()
        self.player.setFocusPolicy(Qt.StrongFocus)
        self.player.settings().setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        self.player.setHtml(PLAYER_HTML, QUrl("https://ytmanager.local/"))
        self.player_frame = FixedVideoFrame(self.player)
        player_layout.addWidget(self.player_frame, alignment=Qt.AlignLeft | Qt.AlignTop)
        _CTRL_BTN_SS = (
            "QPushButton{background:#2a2a2a;color:#ddd;border:none;"
            "border-radius:6px;font-size:15px;padding:4px;}"
            "QPushButton:hover{background:#3a3a3a;}"
            "QPushButton:pressed{background:#1976d2;color:white;}"
            "QPushButton:disabled{color:#555;}"
        )
        _TS_BTN_SS = (
            "QPushButton{background:#2a2a2a;color:#bbb;border:none;"
            "border-radius:6px;padding:4px 10px;font-size:12px;}"
            "QPushButton:hover{background:#3a3a3a;color:#eee;}"
        )
        _CAP_BTN_SS = (
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:6px;padding:4px 14px;font-size:13px;font-weight:bold;}"
            "QPushButton:hover{background:#1976d2;}"
            "QPushButton:disabled{background:#333;color:#666;}"
        )

        # 행 1: seek / play / time
        ctrl_row1 = QHBoxLayout()
        ctrl_row1.setSpacing(4)
        for _icon, _tip, _fn, _w in [
            ("⏪", "5초 뒤로 (←)",         lambda: self._seek_player_relative(-KEYBOARD_SEEK_SECONDS), 36),
            ("◂",  "1프레임 뒤로 (,)",      lambda: self._step_player_frame(-1),                        34),
            ("⏵",  "재생 / 일시정지 (Space)", self._toggle_player_playback,                             38),
            ("▸",  "1프레임 앞으로 (.)",     lambda: self._step_player_frame(1),                        34),
            ("⏩", "5초 앞으로 (→)",         lambda: self._seek_player_relative(KEYBOARD_SEEK_SECONDS), 36),
        ]:
            _b = QPushButton(_icon)
            _b.setToolTip(_tip)
            _b.setFixedSize(_w, 32)
            _b.setStyleSheet(_CTRL_BTN_SS)
            _b.clicked.connect(_fn)
            ctrl_row1.addWidget(_b)
            if _icon == "⏵":
                self.play_pause_btn = _b
        self.player_time_label = QLabel("00:00 / --:--")
        self.player_time_label.setMinimumWidth(115)
        self.player_time_label.setAlignment(Qt.AlignCenter)
        self.player_time_label.setStyleSheet(
            "QLabel{background:#1a1a1a;color:#ddd;border-radius:4px;"
            "padding:2px 6px;font-size:12px;}"
        )
        ctrl_row1.addWidget(self.player_time_label)
        ctrl_row1.addStretch(1)

        # 행 2: timestamp 추가 / 캡처
        ctrl_row2 = QHBoxLayout()
        ctrl_row2.setSpacing(6)
        timestamp_btn = QPushButton("⏱  현재 시점 타임스탬프 추가")
        timestamp_btn.setToolTip("현재 재생 위치를 설명 타임스탬프에 추가")
        timestamp_btn.setStyleSheet(_TS_BTN_SS)
        timestamp_btn.clicked.connect(self.add_current_timestamp)
        self.capture_thumbnail_btn = QPushButton("📸  캡처")
        self.capture_thumbnail_btn.setToolTip("현재 화면을 썸네일 후보로 캡처")
        self.capture_thumbnail_btn.setStyleSheet(_CAP_BTN_SS)
        self.capture_thumbnail_btn.clicked.connect(self.capture_thumbnail_candidate)
        ctrl_row2.addWidget(timestamp_btn, stretch=1)
        ctrl_row2.addWidget(self.capture_thumbnail_btn)

        ctrl_layout = QVBoxLayout()
        ctrl_layout.setSpacing(4)
        ctrl_layout.addLayout(ctrl_row1)
        ctrl_layout.addLayout(ctrl_row2)
        player_layout.addLayout(ctrl_layout)

        self.thumbnail_group = QGroupBox("썸네일 후보 미리보기")
        thumbnail_layout = QHBoxLayout(self.thumbnail_group)
        thumbnail_layout.setContentsMargins(8, 8, 8, 8)
        thumbnail_layout.setSpacing(10)
        self.thumbnail_preview = ThumbnailPreviewLabel("캡처한 썸네일 후보가 여기에 표시됩니다.")
        self.thumbnail_preview.setFixedSize(THUMBNAIL_PREVIEW_WIDTH, THUMBNAIL_PREVIEW_HEIGHT)
        self.thumbnail_preview.setAlignment(Qt.AlignCenter)
        self.thumbnail_preview.setStyleSheet("background-color: #111; color: #aaa; border: 1px solid #333;")
        self.thumbnail_candidate_label = QLabel("후보 없음")
        self.thumbnail_candidate_label.setWordWrap(True)
        thumbnail_actions = QVBoxLayout()
        self.upload_thumbnail_btn = QPushButton("후보 업로드")
        self.upload_thumbnail_btn.clicked.connect(self._upload_last_thumbnail_candidate)
        self.upload_thumbnail_btn.setEnabled(False)
        self.open_thumbnail_preview_btn = QPushButton("웹 썸네일 확인")
        self.open_thumbnail_preview_btn.clicked.connect(self._open_thumbnail_web_preview)
        self.open_thumbnail_preview_btn.setEnabled(False)
        self.open_watch_page_btn = QPushButton("영상 페이지 열기")
        self.open_watch_page_btn.clicked.connect(self._open_video_watch_page)
        self.open_watch_page_btn.setEnabled(False)
        self.waifu2x_status_btn = QPushButton("waifu2x 확인")
        self.waifu2x_status_btn.clicked.connect(self.check_waifu2x_installation)
        thumbnail_actions.addWidget(self.upload_thumbnail_btn)
        thumbnail_actions.addWidget(self.open_thumbnail_preview_btn)
        thumbnail_actions.addWidget(self.open_watch_page_btn)
        thumbnail_actions.addWidget(self.waifu2x_status_btn)
        thumbnail_actions.addStretch(1)
        thumbnail_side = QVBoxLayout()
        thumbnail_side.addWidget(self.thumbnail_candidate_label)
        thumbnail_side.addLayout(thumbnail_actions)
        thumbnail_side.addStretch(1)
        thumbnail_layout.addWidget(self.thumbnail_preview, alignment=Qt.AlignLeft)
        thumbnail_layout.addLayout(thumbnail_side, stretch=1)
        player_layout.addWidget(self.thumbnail_group)
        center_layout.addWidget(self.player_panel, alignment=Qt.AlignLeft | Qt.AlignTop)
        self.timestamp_panel = QWidget()
        timestamp_layout = QVBoxLayout(self.timestamp_panel)
        timestamp_layout.setContentsMargins(0, 0, 0, 0)
        timestamp_layout.setSpacing(4)
        timestamp_layout.addWidget(QLabel("타임스탬프"))
        self.timestamp_editor = QPlainTextEdit()
        self.timestamp_editor.setPlaceholderText("타임스탬프가 여기에 누적됩니다. 예: 01:23 - 보스전 시작")
        self.timestamp_editor.textChanged.connect(self.refresh_description_preview)
        timestamp_layout.addWidget(self.timestamp_editor, stretch=1)
        center_layout.addWidget(self.timestamp_panel, stretch=1)
        self.main_splitter.addWidget(center)

        # --- 오른쪽: 메타데이터 + 미리보기 ---
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # 고정 상단: 제목 · 템플릿 · 상태 · 태그
        right_layout.addWidget(QLabel("제목"))
        self.title_editor = QLineEdit()
        self.title_editor.textChanged.connect(self.refresh_description_preview)
        right_layout.addWidget(self.title_editor)

        template_group = QGroupBox("템플릿")
        template_layout = QHBoxLayout(template_group)
        self.template_button_group = QButtonGroup(self)
        for index, name in enumerate(self.template_library.keys()):
            button = QRadioButton(name)
            self.template_button_group.addButton(button)
            self.template_buttons[name] = button
            template_layout.addWidget(button)
            if index == 0:
                button.setChecked(True)
            button.toggled.connect(self._on_template_changed)
        right_layout.addWidget(template_group)

        self.draft_status_label = QLabel("상태: 영상 미선택")
        self.draft_status_label.setWordWrap(True)
        self.draft_status_label.setMinimumHeight(26)
        self.draft_status_label.setMaximumHeight(48)
        self.draft_status_label.setTextFormat(Qt.RichText)
        right_layout.addWidget(self.draft_status_label)
        right_layout.addWidget(QLabel("상단 태그"))
        self.tags_editor = QLineEdit()
        self.tags_editor.setPlaceholderText("설명 상단 태그 예: #zenlesszonezero #gacha")
        self.tags_editor.textChanged.connect(self.refresh_description_preview)
        right_layout.addWidget(self.tags_editor)

        # 수직 스플리터: [필드+섹션] | [미리보기+diff+버튼]
        right_splitter = QSplitter(Qt.Vertical)
        right_layout.addWidget(right_splitter, stretch=1)

        # 상단: 템플릿 필드(스크롤) / 섹션 트리(combat) — 수직 스플리터로 비율 조절 가능
        meta_panel = QWidget()
        meta_layout = QVBoxLayout(meta_panel)
        meta_layout.setContentsMargins(0, 4, 0, 0)
        meta_layout.setSpacing(4)

        meta_splitter = QSplitter(Qt.Vertical)

        # 필드 영역
        field_widget = QWidget()
        field_vlayout = QVBoxLayout(field_widget)
        field_vlayout.setContentsMargins(0, 0, 0, 0)
        field_vlayout.setSpacing(2)
        field_vlayout.addWidget(QLabel("템플릿 필드"))
        self.field_form_container = QWidget()
        self.field_form = QFormLayout(self.field_form_container)
        self.field_form.setContentsMargins(0, 0, 0, 0)
        field_scroll = QScrollArea()
        field_scroll.setWidget(self.field_form_container)
        field_scroll.setWidgetResizable(True)
        field_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        field_vlayout.addWidget(field_scroll, stretch=1)
        meta_splitter.addWidget(field_widget)

        # 섹션/파티원 트리 영역 (QTreeWidget: 섹션 > 파티원 2단계 계층)
        self.section_panel = QWidget()
        section_layout = QVBoxLayout(self.section_panel)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(4)
        section_header = QHBoxLayout()
        section_header.addWidget(QLabel("섹션 / 파티원"))
        add_section_btn = QPushButton("섹션 추가")
        add_section_btn.clicked.connect(self.add_section_row)
        add_member_btn = QPushButton("파티원 추가")
        add_member_btn.clicked.connect(self.add_party_member_row)
        remove_btn = QPushButton("선택 삭제")
        remove_btn.clicked.connect(self.remove_selected_section_rows)
        section_header.addWidget(add_section_btn)
        section_header.addWidget(add_member_btn)
        section_header.addWidget(remove_btn)
        section_layout.addLayout(section_header)
        self.section_tree = QTreeWidget()
        self.section_tree.setColumnCount(4)
        self.section_tree.setHeaderLabels(["단계", "보스 / 캐릭터", "파티 구성 / 돌파", "장비"])
        self.section_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.section_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.section_tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.section_tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        self.section_tree.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.section_tree.itemChanged.connect(self.refresh_description_preview)
        section_layout.addWidget(self.section_tree, stretch=1)
        meta_splitter.addWidget(self.section_panel)
        meta_splitter.setSizes([160, 240])

        meta_layout.addWidget(meta_splitter, stretch=1)
        right_splitter.addWidget(meta_panel)

        # 하단: 설명 미리보기 + diff + 액션 버튼
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)
        preview_layout.addWidget(QLabel("설명 미리보기"))
        self.description_editor = QPlainTextEdit()
        self.description_editor.setReadOnly(True)
        preview_layout.addWidget(self.description_editor, stretch=2)
        preview_layout.addWidget(QLabel("변경사항 diff"))
        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        preview_layout.addWidget(self.diff_view, stretch=1)
        draft_buttons = QHBoxLayout()
        save_btn = QPushButton("초안 저장")
        save_btn.clicked.connect(self.save_current_draft)
        reviewed_btn = QPushButton("검수 완료")
        reviewed_btn.clicked.connect(self.mark_current_reviewed)
        reviewed_btn.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;border-radius:4px;padding:5px 10px;}"
            "QPushButton:hover{background:#388e3c;}"
        )
        unreview_btn = QPushButton("검수 해제")
        unreview_btn.clicked.connect(self.unreview_current_draft)
        apply_selected_btn = QPushButton("선택 적용")
        apply_selected_btn.clicked.connect(self.apply_selected_draft)
        apply_selected_btn.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;font-weight:bold;"
            "border-radius:4px;padding:5px 10px;}"
            "QPushButton:hover{background:#1976d2;}"
        )
        draft_buttons.addWidget(save_btn)
        draft_buttons.addWidget(reviewed_btn)
        draft_buttons.addWidget(unreview_btn)
        draft_buttons.addWidget(apply_selected_btn)
        preview_layout.addLayout(draft_buttons)
        right_splitter.addWidget(preview_panel)
        right_splitter.setSizes([380, 480])

        self.main_splitter.addWidget(self.right_panel)
        self.main_splitter.setSizes([760, 580])

        # 패널 크기 제약 (겹침·잘림 방지)
        center.setMinimumWidth(660)
        self.right_panel.setMinimumWidth(400)
        self.title_editor.setMinimumHeight(28)
        self.section_tree.setMinimumHeight(80)
        field_widget.setMinimumHeight(60)

        # MetaData 모드가 기본 — 썸네일 섹션 숨김
        self.thumbnail_group.setVisible(False)

        self.setStatusBar(QStatusBar())
        self.workspace_stack.addWidget(self.metadata_workspace)
        self.local_upload_widget = LocalUploadWidget(
            rules=self.rule_mappings,
            settings_store=self.db,
            ensure_youtube_client=self._ensure_youtube_client_for_local_upload,
            status_message=lambda message: self.statusBar().showMessage(message),
            refresh_uploaded_videos=self.sync_videos,
            parent=self,
        )
        self.workspace_stack.addWidget(self.local_upload_widget)
        if self.local_upload_widget.restored_session_loaded:
            self.local_workspace_btn.setChecked(True)

        self.statusBar().showMessage("준비됨")
        self._rebuild_field_form(self._selected_template_name(), {})

    def login(self) -> None:
        try:
            service = self.oauth.build_youtube_service(write_access=True)
            self.youtube = YouTubeApiClient(service)
            self.statusBar().showMessage("Google 로그인 완료")
            QMessageBox.information(self, "로그인 완료", "Google 계정 연동이 완료되었습니다.")
        except OAuthSetupError as exc:
            QMessageBox.warning(self, "로그인 설정 필요", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "로그인 실패", f"Google 로그인 중 오류가 발생했습니다.\n\n{exc}")

    def _ensure_youtube_client_for_local_upload(self) -> Optional[YouTubeApiClient]:
        if not self.youtube:
            self.login()
        return self.youtube

    def _restore_google_session_if_available(self) -> None:
        if self.youtube or not self.oauth.has_saved_login():
            return
        try:
            service = self.oauth.build_cached_youtube_service(write_access=True)
        except Exception:
            service = None
        if service is None:
            return
        self.youtube = YouTubeApiClient(service)
        self.statusBar().showMessage("저장된 Google 로그인 상태를 복원했습니다.")

    def _set_workspace(self, index: int, checked: bool) -> None:
        if not checked:
            return
        self.workspace_stack.setCurrentIndex(index)
        if index == 1:
            self.statusBar().showMessage("로컬 편집 작업 공간으로 전환했습니다.")
        else:
            self.statusBar().showMessage("YouTube 메타데이터 작업 공간으로 전환했습니다.")

    def sync_videos(self) -> None:
        if not self.youtube:
            self.login()
            if not self.youtube:
                return
        try:
            videos = self.youtube.list_uploaded_videos(limit=200)
            self.db.save_videos(videos)
            self._generate_drafts(videos)
            self._populate_videos(videos)
            self.statusBar().showMessage(f"영상 {len(videos)}개를 동기화하고 정규화 초안을 갱신했습니다.")
        except Exception as exc:
            QMessageBox.critical(self, "동기화 실패", f"영상 목록을 가져오지 못했습니다.\n\n{exc}")

    def generate_drafts_for_cached_videos(self) -> None:
        videos = self.db.list_videos()
        created = self._generate_drafts(videos)
        self._populate_videos(videos)
        QMessageBox.information(self, "초안 생성", f"정규화 초안 {created}개를 저장했습니다.\n검수 완료/적용 완료 상태의 초안은 덮어쓰지 않았습니다.")

    def _generate_drafts(self, videos: list[VideoSummary]) -> int:
        candidates = build_migration_candidates(videos, self.template_text, self.rule_mappings)
        saved = 0
        for candidate in candidates:
            draft = candidate_to_record(candidate)
            if self.db.save_description_draft(draft, preserve_reviewed=True):
                self.db.observe_draft_roster(candidate.video, draft)
                saved += 1
        return saved

    def _load_cached_videos(self) -> None:
        self._populate_videos(self.db.list_videos())

    _STATUS_ICON: dict[str | None, tuple[str, str]] = {
        DRAFT_STATUS_DRAFT:     ("✏", "#e6b800"),   # 초안 — 노란색
        DRAFT_STATUS_REVIEWED:  ("✓", "#4caf50"),   # 검수 완료 — 초록
        DRAFT_STATUS_APPLIED:   ("✔", "#2196f3"),   # 적용 완료 — 파랑
        DRAFT_STATUS_ERROR:     ("✗", "#f44336"),   # 오류 — 빨강
        DRAFT_STATUS_SKIPPED:   ("—", "#888888"),   # 건너뜀 — 회색
        None:                   ("·", "#888888"),   # 미생성 / 대상 제외 — 회색
    }

    def _populate_videos(self, videos: list[VideoSummary]) -> None:
        self.video_list.clear()
        status_map = self.db.draft_status_map()
        for video in videos:
            status = status_map.get(video.video_id)
            # 관리 대상이 아닌 영상은 건너뜀으로 표시
            if status is None and not is_managed_title(video.title):
                status = DRAFT_STATUS_SKIPPED
            icon, color = self._STATUS_ICON.get(status, self._STATUS_ICON[None])
            item = QListWidgetItem(f"{icon}  {video.title}")
            item.setForeground(QColor(color))
            tooltip_lines = [video.title, f"상태: {STATUS_LABELS.get(status or '', '미생성')}"]
            item.setToolTip("\n".join(tooltip_lines))
            item.setData(Qt.UserRole, video)
            self.video_list.addItem(item)

    def _filter_video_list(self, text: str) -> None:
        keyword = text.strip().casefold()
        for index in range(self.video_list.count()):
            item = self.video_list.item(index)
            item.setHidden(keyword not in item.text().casefold())

    def _on_video_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if not current:
            return
        video = current.data(Qt.UserRole)
        if not isinstance(video, VideoSummary):
            return
        self.current_video = video
        self.current_draft = VideoDraft.from_video(video)
        self._reset_thumbnail_candidate()
        self._player_duration = 0.0
        self._set_player_time_label(0, 0)
        self.player.page().runJavaScript(f"loadVideo({video.video_id!r});")
        draft = self.db.get_description_draft(video.video_id)
        if draft is None and is_managed_title(video.title):
            candidate = build_normalized_description(video, self.template_text, self.rule_mappings)
            draft = candidate_to_record(candidate)
            self.db.save_description_draft(draft)
            self.db.observe_draft_roster(video, draft)
        self._load_draft_into_ui(video, draft)
        self.statusBar().showMessage(f"선택됨: {video.title} · 원본 {video.resolution_label()} · 재생기 16:9 고정")

    def _reset_thumbnail_candidate(self) -> None:
        self.last_thumbnail_candidate = None
        self.thumbnail_preview.clear()
        self.thumbnail_preview.clear_candidate()
        self.thumbnail_preview.setText("캡처한 썸네일 후보가 여기에 표시됩니다.")
        self.thumbnail_candidate_label.setText("후보 없음")
        if hasattr(self, "capture_thumbnail_btn"):
            self.capture_thumbnail_btn.setEnabled(bool(self.current_video))
        self.upload_thumbnail_btn.setEnabled(False)
        self.open_thumbnail_preview_btn.setEnabled(bool(self.current_video))
        self.open_watch_page_btn.setEnabled(bool(self.current_video))

    def _set_thumbnail_processing(self, processing: bool) -> None:
        if hasattr(self, "capture_thumbnail_btn"):
            self.capture_thumbnail_btn.setEnabled(not processing and bool(self.current_video))
        self.upload_thumbnail_btn.setEnabled(not processing and bool(self.last_thumbnail_candidate))
        if processing:
            self.open_thumbnail_preview_btn.setEnabled(False)
            self.open_watch_page_btn.setEnabled(False)
        else:
            self.open_thumbnail_preview_btn.setEnabled(bool(self.current_video))
            self.open_watch_page_btn.setEnabled(bool(self.current_video))

    def _load_draft_into_ui(self, video: VideoSummary, draft: DescriptionDraftRecord | None) -> None:
        self._loading_ui = True
        self.current_description_draft = draft
        self.title_editor.setText(video.title)
        self.section_tree.clear()
        self.timestamp_editor.setPlainText("")
        if draft is None:
            self._set_template_name("combat")
            self.section_panel.setVisible(True)
            self.tags_editor.setText("")
            self._rebuild_field_form(self._selected_template_name(), {})
            self.description_editor.setPlainText(video.description)
            self._set_draft_status_label("상태: 작업 대상 제외")
            self._loading_ui = False
            self.refresh_diff()
            return
        self._set_template_name(draft.template_name)
        self.section_panel.setVisible(draft.template_name != "gacha")
        self.tags_editor.setText(" ".join(draft.top_tags))
        self._rebuild_field_form(draft.template_name, draft.fields)
        self._set_sections_from_json(draft.sections)
        self._set_timestamps_from_json(draft.timestamps)
        self.description_editor.setPlainText(draft.rendered_description)
        self._set_draft_status_label(self._draft_status_text(draft))
        self._loading_ui = False
        self.refresh_description_preview()

    _STATUS_BADGE: dict[str | None, str] = {
        DRAFT_STATUS_DRAFT:    "background:#e6b800;color:#111",
        DRAFT_STATUS_REVIEWED: "background:#2e7d32;color:white",
        DRAFT_STATUS_APPLIED:  "background:#1565c0;color:white",
        DRAFT_STATUS_ERROR:    "background:#c62828;color:white",
    }

    def _draft_status_text(self, draft: DescriptionDraftRecord) -> str:
        ss = self._STATUS_BADGE.get(draft.status, "background:#555;color:#ccc")
        label = STATUS_LABELS.get(draft.status, draft.status or "—")
        badge = f'<span style="{ss};border-radius:3px;padding:1px 6px">&nbsp;{label}&nbsp;</span>'
        parts = [badge]
        if draft.parse_confidence:
            parts.append(f"신뢰도: {draft.parse_confidence}")
        if draft.warnings or draft.unmatched_lines:
            issues = len(draft.warnings) + len(draft.unmatched_lines)
            parts.append(f'<span style="color:#e6b800">⚠ 확인필요: {issues}건</span>')
        if draft.error_message:
            parts.append(f'<span style="color:#f44336">오류: {draft.error_message}</span>')
        return "&nbsp;·&nbsp;".join(parts)

    def _set_draft_status_label(self, text: str) -> None:
        self.draft_status_label.setText(text)

    def _selected_template_name(self) -> str:
        for name, button in self.template_buttons.items():
            if button.isChecked():
                return name
        return next(iter(self.template_library.keys()), "combat")

    def _set_template_name(self, name: str) -> None:
        button = self.template_buttons.get(name) or self.template_buttons.get("combat")
        if button:
            button.setChecked(True)

    def _on_template_changed(self, checked: bool = False) -> None:
        del checked
        if self._loading_ui:
            return
        template_name = self._selected_template_name()
        self.section_panel.setVisible(template_name != "gacha")
        self._rebuild_field_form(template_name, self._current_fields())
        self.refresh_description_preview()

    def _rebuild_field_form(self, template_name: str, values: dict[str, str]) -> None:
        while self.field_form.rowCount():
            self.field_form.removeRow(0)
        self.field_edits = {}
        placeholders = extract_placeholders(select_template(self.template_text, template_name))
        field_names = [name for name in placeholders if self._is_general_field_name(name)]
        if template_name == "freeform" and "body" not in field_names:
            field_names.append("body")
        for name in field_names:
            edit = QLineEdit()
            edit.setText(values.get(name, ""))
            edit.textChanged.connect(self.refresh_description_preview)
            label = QLabel(name)
            label.setMinimumWidth(60)
            label.setMaximumWidth(130)
            label.setToolTip(name)
            self.field_form.addRow(label, edit)
            self.field_edits[name] = edit

    def _is_general_field_name(self, name: str) -> bool:
        return name not in FIELD_EXCLUDES and "[i]" not in name and not name.startswith("party")

    def _current_fields(self) -> dict[str, str]:
        return {name: edit.text().strip() for name, edit in self.field_edits.items() if edit.text().strip()}

    def add_section_row(self) -> None:
        item = QTreeWidgetItem(self.section_tree, ["", "", "", ""])
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        item.setExpanded(True)
        self.section_tree.setCurrentItem(item)
        self.refresh_description_preview()

    def add_party_member_row(self) -> None:
        current = self.section_tree.currentItem()
        if current is None:
            count = self.section_tree.topLevelItemCount()
            if count == 0:
                return
            parent = self.section_tree.topLevelItem(count - 1)
        elif current.parent() is None:
            parent = current
        else:
            parent = current.parent()
        member = QTreeWidgetItem(parent, ["", "", "", ""])
        member.setFlags(member.flags() | Qt.ItemIsEditable)
        parent.setExpanded(True)
        self.section_tree.setCurrentItem(member)
        self._attach_character_completer(member)
        self.refresh_description_preview()

    def _character_completion_values(self) -> list[str]:
        if not self.current_video:
            return []
        game_key = game_key_from_title_prefix(extract_title_prefix(self.current_video.title))
        values: list[str] = []
        for suggestion in self.db.character_suggestions(game_key, limit=500):
            label = suggestion.display_name
            if suggestion.owned_status:
                label = f"{label} ({suggestion.owned_status})"
            values.append(label)
            values.extend(suggestion.aliases)
        return sorted(dict.fromkeys(value for value in values if value))

    def _attach_character_completer(self, item: QTreeWidgetItem) -> None:
        editor = QLineEdit()
        editor.setText(item.text(1))
        completer = QCompleter(self._character_completion_values(), editor)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        editor.setCompleter(completer)
        editor.editingFinished.connect(lambda: self._commit_character_editor(item, editor))
        self.section_tree.setItemWidget(item, 1, editor)

    def _commit_character_editor(self, item: QTreeWidgetItem, editor: QLineEdit) -> None:
        value = editor.text().strip()
        if " (" in value and value.endswith(")"):
            value = value.rsplit(" (", 1)[0]
        item.setText(1, value)
        self.refresh_description_preview()

    def remove_selected_section_rows(self) -> None:
        for item in list(self.section_tree.selectedItems()):
            parent = item.parent()
            if parent is None:
                idx = self.section_tree.indexOfTopLevelItem(item)
                self.section_tree.takeTopLevelItem(idx)
            else:
                parent.removeChild(item)
        self.refresh_description_preview()

    def _sections_from_tree(self) -> list[DescriptionSection]:
        sections: list[DescriptionSection] = []
        game_key = game_key_from_title_prefix(extract_title_prefix(self.current_video.title if self.current_video else ""))
        for i in range(self.section_tree.topLevelItemCount()):
            sec = self.section_tree.topLevelItem(i)
            stage_number = sec.text(0).strip()
            boss_name = sec.text(1).strip()
            party_composition = sec.text(2).strip()
            party: list[PartyMember] = []
            for j in range(sec.childCount()):
                mem = sec.child(j)
                character = mem.text(1).strip()
                m_level = mem.text(2).strip()
                equip = mem.text(3).strip()
                if character:
                    parsed = parse_party_status(" ".join(part for part in (m_level, equip) if part), game_key)
                    party.append(
                        PartyMember(
                            character=character,
                            m_level=format_party_status(parsed, game_key),
                            equip="",
                            raw_name=character,
                            canonical_name=character,
                            character_rank=parsed.character_rank,
                            character_rank_value=parsed.character_rank_value,
                            equipment_type=parsed.equipment_type,
                            equipment_rank=parsed.equipment_rank,
                            equipment_rank_value=parsed.equipment_rank_value,
                            raw_status=parsed.raw_status,
                            parse_warnings=parsed.warnings,
                        )
                    )
            if boss_name or stage_number:
                sections.append(DescriptionSection(
                    stage_number=stage_number,
                    boss_name=boss_name,
                    party_composition=party_composition,
                    party=tuple(party),
                ))
        return sections

    def _set_sections_from_json(self, sections: list[dict[str, object]]) -> None:
        self.section_tree.blockSignals(True)
        self.section_tree.clear()
        for section in sections:
            if not isinstance(section, dict):
                continue
            stage_number = str(section.get("stage_number", ""))
            boss_name = str(section.get("boss_name", ""))
            party_composition = str(section.get("party_composition", ""))
            sec_item = QTreeWidgetItem(self.section_tree, [stage_number, boss_name, party_composition, ""])
            sec_item.setFlags(sec_item.flags() | Qt.ItemIsEditable)
            party = section.get("party", [])
            if isinstance(party, list):
                for member in party:
                    if isinstance(member, dict):
                        mem_item = QTreeWidgetItem(sec_item, [
                            "",
                            str(member.get("character", "")),
                            str(member.get("m_level", "")),
                            str(member.get("equip", "")),
                        ])
                        mem_item.setFlags(mem_item.flags() | Qt.ItemIsEditable)
                        self._attach_character_completer(mem_item)
            sec_item.setExpanded(True)
        self.section_tree.blockSignals(False)

    def _timestamps_from_editor(self) -> list[TimestampEntry]:
        entries: list[TimestampEntry] = []
        for line in self.timestamp_editor.toPlainText().splitlines():
            if not line.strip():
                continue
            stamp, _, label = line.partition("-")
            try:
                seconds = parse_timestamp(stamp.strip())
            except ValueError:
                continue
            entries.append(TimestampEntry(seconds, label.strip()))
        return entries

    def _set_timestamps_from_json(self, timestamps: list[dict[str, object]]) -> None:
        lines = []
        for timestamp in timestamps:
            try:
                seconds = float(timestamp.get("seconds", 0))
            except (AttributeError, TypeError, ValueError):
                continue
            label = str(timestamp.get("label", "")) if isinstance(timestamp, dict) else ""
            line = f"{format_timestamp(seconds)} - {label}" if label else format_timestamp(seconds)
            lines.append(line)
        self.timestamp_editor.setPlainText("\n".join(lines))

    def _top_tags_from_editor(self) -> list[str]:
        return [token.strip() for token in self.tags_editor.text().split() if token.strip()]

    def refresh_description_preview(self, *args) -> None:
        del args
        if self._loading_ui or not self.current_video:
            return
        template_name = self._selected_template_name()
        description = render_description_template(
            self.template_text,
            template_name,
            fields=self._current_fields(),
            top_tags=self._top_tags_from_editor(),
            timestamps=self._timestamps_from_editor(),
            sections=self._sections_from_tree(),
        )
        if self.description_editor.toPlainText() != description:
            self.description_editor.setPlainText(description)
        self.refresh_diff()

    def refresh_diff(self) -> None:
        if not self.current_video:
            self.diff_view.setPlainText("")
            return
        before = self.current_video.description.splitlines()
        after = self.description_editor.toPlainText().splitlines()
        diff = difflib.unified_diff(before, after, fromfile="현재 YouTube 설명", tofile="적용 예정 설명", lineterm="")
        self.diff_view.setPlainText("\n".join(diff))

    def _draft_from_ui(self, status: str | None = None) -> Optional[DescriptionDraftRecord]:
        if not self.current_video:
            return None
        previous = self.current_description_draft
        new_status = status or (previous.status if previous else DRAFT_STATUS_DRAFT)
        reviewed_at = previous.reviewed_at if previous else None
        if new_status == DRAFT_STATUS_REVIEWED and not reviewed_at:
            reviewed_at = utc_now_iso()
        if new_status == DRAFT_STATUS_DRAFT:
            reviewed_at = None
        sections = self._sections_from_tree()
        timestamps = self._timestamps_from_editor()
        return DescriptionDraftRecord(
            video_id=self.current_video.video_id,
            template_name=self._selected_template_name(),
            status=new_status,
            fields=self._current_fields(),
            sections=[section_to_json(section) for section in sections],
            timestamps=[{"seconds": timestamp.seconds, "label": timestamp.label} for timestamp in timestamps],
            top_tags=self._top_tags_from_editor(),
            rendered_description=self.description_editor.toPlainText().strip(),
            parse_confidence=previous.parse_confidence if previous else "manual",
            warnings=previous.warnings if previous else [],
            unmatched_lines=previous.unmatched_lines if previous else [],
            reviewed_at=reviewed_at,
            applied_at=previous.applied_at if previous else None,
        )

    def save_current_draft(self) -> None:
        draft = self._draft_from_ui(DRAFT_STATUS_DRAFT)
        if not draft:
            return
        self.db.save_description_draft(draft, preserve_reviewed=False)
        if self.current_video:
            self.db.observe_draft_roster(self.current_video, draft)
        self.current_description_draft = self.db.get_description_draft(draft.video_id)
        if self.current_description_draft:
            self._set_draft_status_label(self._draft_status_text(self.current_description_draft))
        self._load_cached_videos()
        self.statusBar().showMessage("초안을 저장했습니다.")

    def mark_current_reviewed(self) -> None:
        draft = self._draft_from_ui(DRAFT_STATUS_REVIEWED)
        if not draft:
            return
        self.db.save_description_draft(draft, preserve_reviewed=False)
        if self.current_video:
            self.db.observe_draft_roster(self.current_video, draft)
        self.current_description_draft = self.db.get_description_draft(draft.video_id)
        if self.current_description_draft:
            self._set_draft_status_label(self._draft_status_text(self.current_description_draft))
        self._load_cached_videos()
        self.statusBar().showMessage("검수 완료로 표시했습니다.")

    def unreview_current_draft(self) -> None:
        draft = self._draft_from_ui(DRAFT_STATUS_DRAFT)
        if not draft:
            return
        self.db.save_description_draft(draft, preserve_reviewed=False)
        if self.current_video:
            self.db.observe_draft_roster(self.current_video, draft)
        self.current_description_draft = self.db.get_description_draft(draft.video_id)
        if self.current_description_draft:
            self._set_draft_status_label(self._draft_status_text(self.current_description_draft))
        self._load_cached_videos()
        self.statusBar().showMessage("검수 완료 상태를 해제했습니다.")

    def _install_player_shortcuts(self) -> None:
        shortcuts: tuple[tuple[QKeySequence, Callable[[], None], bool], ...] = (
            (QKeySequence(Qt.Key_Space), self._handle_space_shortcut, True),
            (QKeySequence(Qt.Key_Left), self._handle_left_shortcut, True),
            (QKeySequence(Qt.Key_Right), self._handle_right_shortcut, True),
            (QKeySequence(Qt.Key_Comma), self._handle_comma_shortcut, True),
            (QKeySequence(Qt.Key_Period), self._handle_period_shortcut, True),
            (QKeySequence("Ctrl+P"), self._handle_ctrl_p_shortcut, False),
            (QKeySequence("Ctrl+S"), self._handle_ctrl_s_shortcut, False),
        )
        for sequence, action, block_when_typing in shortcuts:
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(
                lambda action=action, block_when_typing=block_when_typing: self._run_workspace_shortcut(action, block_when_typing)
            )
            self._player_shortcuts.append(shortcut)

    def _run_workspace_shortcut(self, action: Callable[[], None], block_when_typing: bool) -> None:
        if block_when_typing:
            if self._is_local_workspace_active():
                if self.local_upload_widget.is_text_input_focused():
                    return
            elif self._player_shortcut_blocked():
                return
        action()

    def _player_shortcut_blocked(self) -> bool:
        focus = self.focusWidget()
        while focus:
            if isinstance(focus, (QLineEdit, QPlainTextEdit)):
                return True
            focus = focus.parentWidget()
        return False

    def _is_local_workspace_active(self) -> bool:
        return hasattr(self, "workspace_stack") and self.workspace_stack.currentIndex() == 1

    def _handle_space_shortcut(self) -> None:
        if self._is_local_workspace_active():
            self.local_upload_widget.toggle_playback()
            return
        if self.current_video:
            self._toggle_player_playback()

    def _handle_left_shortcut(self) -> None:
        if self._is_local_workspace_active():
            self.local_upload_widget.seek_prev_keyframe()
            return
        if self.current_video:
            self._seek_player_relative(-KEYBOARD_SEEK_SECONDS)

    def _handle_right_shortcut(self) -> None:
        if self._is_local_workspace_active():
            self.local_upload_widget.seek_next_keyframe()
            return
        if self.current_video:
            self._seek_player_relative(KEYBOARD_SEEK_SECONDS)

    def _handle_comma_shortcut(self) -> None:
        if self._is_local_workspace_active():
            self.local_upload_widget.step_frame(-1)
            return
        if self.current_video:
            self._step_player_frame(-1)

    def _handle_period_shortcut(self) -> None:
        if self._is_local_workspace_active():
            self.local_upload_widget.step_frame(1)
            return
        if self.current_video:
            self._step_player_frame(1)

    def _handle_ctrl_p_shortcut(self) -> None:
        if self._is_local_workspace_active():
            self.local_upload_widget.capture_current_thumbnail()
            return
        if self.current_video:
            self.capture_thumbnail_candidate()

    def _handle_ctrl_s_shortcut(self) -> None:
        if self._is_local_workspace_active():
            self.local_upload_widget.save_session_now()

    def _toggle_player_playback(self) -> None:
        if not self.current_video:
            return
        self.player.page().runJavaScript("togglePlayPause();")

    def _step_player_frame(self, direction: int) -> None:
        if not self.current_video:
            return
        self.player.page().runJavaScript(
            f"stepFrame({direction}, {DEFAULT_FRAME_STEP_FPS});",
            self._on_player_position_changed,
        )

    def _seek_player_relative(self, seconds: int) -> None:
        if not self.current_video:
            return
        self.player.page().runJavaScript(f"seekRelative({seconds});", self._on_player_position_changed)

    def _on_player_position_changed(self, value: object) -> None:
        try:
            seconds = float(value or 0)
        except (TypeError, ValueError):
            return
        self.statusBar().showMessage(f"재생 위치: {format_timestamp(seconds)} ({seconds:.3f}s)")
        self._set_player_time_label(seconds, self._player_duration)

    def _refresh_player_time(self) -> None:
        if not self.current_video:
            self._set_player_time_label(0, 0)
            return
        self.player.page().runJavaScript("getPlayerSnapshotSafe();", self._update_player_snapshot)

    def _update_player_snapshot(self, value: object) -> None:
        if not isinstance(value, dict):
            return
        try:
            current = float(value.get("currentTime") or 0)
            duration = float(value.get("duration") or 0)
            state = int(value.get("state") or 0)
        except (TypeError, ValueError):
            return
        self._player_duration = duration
        self._set_player_time_label(current, duration)
        if hasattr(self, "play_pause_btn"):
            self.play_pause_btn.setText("⏸" if state == 1 else "⏵")

    def _set_player_time_label(self, current: float, duration: float) -> None:
        if not hasattr(self, "player_time_label"):
            return
        duration_text = format_timestamp(duration) if duration > 0 else "--:--"
        self.player_time_label.setText(f"{format_timestamp(current)} / {duration_text}")

    def add_current_timestamp(self) -> None:
        if not self.current_video:
            QMessageBox.information(self, "영상 선택 필요", "먼저 영상을 선택하세요.")
            return
        self.player.page().runJavaScript("getCurrentTimeSafe();", self._append_timestamp_from_js)

    def _append_timestamp_from_js(self, value: object) -> None:
        try:
            seconds = float(value or 0)
        except (TypeError, ValueError):
            seconds = 0
        existing = self.timestamp_editor.toPlainText().rstrip()
        line = f"{format_timestamp(seconds)} - "
        self.timestamp_editor.setPlainText(f"{existing}\n{line}".lstrip())
        cursor = self.timestamp_editor.textCursor()
        cursor.movePosition(cursor.End)
        self.timestamp_editor.setTextCursor(cursor)

    def capture_thumbnail_candidate(self) -> None:
        if not self.current_video:
            QMessageBox.information(self, "영상 선택 필요", "먼저 영상을 선택하세요.")
            return
        self.statusBar().showMessage("현재 렌더러 화면을 썸네일 후보로 캡처합니다...")
        QTimer.singleShot(250, self._do_capture_thumbnail)

    def _do_capture_thumbnail(self) -> None:
        if not self.current_video:
            return
        cache_dir = user_cache_dir()
        raw_target = cache_dir / f"thumbnail-{self.current_video.video_id}-raw.png"
        suffix = "png" if THUMBNAIL_KEEP_UPSCALED_PNG else "jpg"
        final_target = cache_dir / f"thumbnail-{self.current_video.video_id}.{suffix}"
        pixmap = self._trim_black_borders(self.player.grab())
        if not pixmap.save(str(raw_target), "PNG"):
            QMessageBox.warning(self, "캡처 실패", "현재 재생 화면을 원본 후보 이미지로 저장하지 못했습니다.")
            return
        if self.thumbnail_upscale_worker and self.thumbnail_upscale_worker.isRunning():
            QMessageBox.information(self, "처리 중", "이미 썸네일 업스케일 처리가 진행 중입니다.")
            return
        self.thumbnail_candidate_label.setText("썸네일 후보 복원/업스케일 중...")
        self.statusBar().showMessage("썸네일 후보 복원/업스케일 중... 최초 실행 시 waifu2x를 다운로드할 수 있습니다.")
        self._set_thumbnail_processing(True)
        worker = ThumbnailUpscaleWorker(raw_target, final_target)
        self.thumbnail_upscale_worker = worker
        worker.finished_result.connect(self._on_thumbnail_upscale_finished)
        worker.failed.connect(self._on_thumbnail_upscale_failed)
        worker.finished.connect(self._on_thumbnail_upscale_worker_finished)
        worker.start()

    def _on_thumbnail_upscale_finished(self, result: object) -> None:
        if not isinstance(result, UpscaleResult):
            self._on_thumbnail_upscale_failed("업스케일 결과 형식이 올바르지 않습니다.")
            return
        pixmap = QPixmap(str(result.output_path))
        if pixmap.isNull():
            self._on_thumbnail_upscale_failed("업스케일된 썸네일 후보 이미지를 열 수 없습니다.")
            return
        validation = validate_thumbnail_file(result.output_path)
        if not validation.can_upload:
            if result.output_path.suffix.lower() != ".png":
                QMessageBox.warning(self, "썸네일 검증 실패", validation.message)
                self.statusBar().showMessage(f"썸네일 검증 실패: {validation.message}")
                self._set_thumbnail_processing(False)
                return
            self.statusBar().showMessage(f"PNG 비교 후보 생성 완료: {validation.message}")
        self._set_thumbnail_candidate(result.output_path, pixmap, result.message)
        fallback_note = " (fallback)" if result.fallback_used else ""
        self.statusBar().showMessage(f"썸네일 후보 저장 완료{fallback_note}: {result.output_path}")
        self._set_thumbnail_processing(False)

    def _on_thumbnail_upscale_failed(self, message: str) -> None:
        QMessageBox.warning(self, "업스케일 실패", f"썸네일 후보 업스케일 중 오류가 발생했습니다.\n\n{message}")
        self.thumbnail_candidate_label.setText(f"업스케일 실패: {message}")
        self.statusBar().showMessage(f"업스케일 실패: {message}")
        self._set_thumbnail_processing(False)

    def _on_thumbnail_upscale_worker_finished(self) -> None:
        self.thumbnail_upscale_worker = None

    def check_waifu2x_installation(self) -> None:
        status = waifu2x_status()
        if status.available:
            QMessageBox.information(
                self,
                "waifu2x 준비 완료",
                f"{status.message}\n\n플랫폼: {status.platform_key}\n캐시: {status.cache_dir}",
            )
            self.statusBar().showMessage(status.message)
            return
        if self.waifu2x_install_worker and self.waifu2x_install_worker.isRunning():
            QMessageBox.information(self, "waifu2x 준비 중", "이미 waifu2x 다운로드/설치 확인이 진행 중입니다.")
            return
        self.statusBar().showMessage("waifu2x 다운로드/설치 확인 중...")
        self.waifu2x_status_btn.setEnabled(False)
        worker = Waifu2xInstallWorker()
        self.waifu2x_install_worker = worker
        worker.finished_result.connect(self._on_waifu2x_install_finished)
        worker.failed.connect(self._on_waifu2x_install_failed)
        worker.finished.connect(self._on_waifu2x_install_worker_finished)
        worker.start()

    def _on_waifu2x_install_finished(self, executable: object) -> None:
        status = waifu2x_status()
        message = status.message if status.available else f"waifu2x 준비 결과 확인 필요: {executable}"
        QMessageBox.information(
            self,
            "waifu2x 준비 완료",
            f"{message}\n\n플랫폼: {status.platform_key}\n캐시: {status.cache_dir}",
        )
        self.statusBar().showMessage(message)
        self.thumbnail_candidate_label.setText(message if not self.last_thumbnail_candidate else self.thumbnail_candidate_label.text())

    def _on_waifu2x_install_failed(self, message: str) -> None:
        status = waifu2x_status()
        QMessageBox.warning(
            self,
            "waifu2x 준비 실패",
            f"waifu2x 다운로드/설치 확인에 실패했습니다.\n\n{message}\n\n캐시: {status.cache_dir}\nURL: {status.archive_url}",
        )
        self.statusBar().showMessage(f"waifu2x 준비 실패: {message}")

    def _on_waifu2x_install_worker_finished(self) -> None:
        self.waifu2x_install_worker = None
        self.waifu2x_status_btn.setEnabled(True)

    def _trim_black_borders(self, pixmap: QPixmap) -> QPixmap:
        if pixmap.isNull():
            return pixmap
        image = pixmap.toImage()
        width = image.width()
        height = image.height()
        if width <= 0 or height <= 0:
            return pixmap

        x_step = max(1, width // 240)
        y_step = max(1, height // 180)

        def is_black(x: int, y: int) -> bool:
            color = QColor(image.pixel(x, y))
            return (
                color.red() <= BLACK_BORDER_THRESHOLD
                and color.green() <= BLACK_BORDER_THRESHOLD
                and color.blue() <= BLACK_BORDER_THRESHOLD
            )

        def mostly_black_row(y: int) -> bool:
            samples = 0
            black = 0
            for x in range(0, width, x_step):
                samples += 1
                if is_black(x, y):
                    black += 1
            return samples > 0 and black / samples >= 0.98

        def mostly_black_column(x: int) -> bool:
            samples = 0
            black = 0
            for y in range(0, height, y_step):
                samples += 1
                if is_black(x, y):
                    black += 1
            return samples > 0 and black / samples >= 0.98

        top = 0
        while top < height and mostly_black_row(top):
            top += 1
        bottom = height - 1
        while bottom > top and mostly_black_row(bottom):
            bottom -= 1
        left = 0
        while left < width and mostly_black_column(left):
            left += 1
        right = width - 1
        while right > left and mostly_black_column(right):
            right -= 1

        crop_width = right - left + 1
        crop_height = bottom - top + 1
        if crop_width <= 0 or crop_height <= 0:
            return pixmap
        if min(top, height - 1 - bottom, left, width - 1 - right) < 0:
            return pixmap
        if max(top, height - 1 - bottom, left, width - 1 - right) < BLACK_BORDER_MIN_CROP_PX:
            return pixmap
        if crop_width < width * 0.45 or crop_height < height * 0.45:
            return pixmap
        return pixmap.copy(left, top, crop_width, crop_height)

    def _resize_thumbnail_candidate(self, pixmap: QPixmap) -> QPixmap:
        if pixmap.isNull():
            return pixmap
        aspect = pixmap.width() / pixmap.height() if pixmap.height() else 0
        target_aspect = THUMBNAIL_EXPORT_WIDTH / THUMBNAIL_EXPORT_HEIGHT
        if abs(aspect - target_aspect) > 0.05:
            return pixmap
        if pixmap.width() == THUMBNAIL_EXPORT_WIDTH and pixmap.height() == THUMBNAIL_EXPORT_HEIGHT:
            return pixmap
        return pixmap.scaled(THUMBNAIL_EXPORT_WIDTH, THUMBNAIL_EXPORT_HEIGHT, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _set_thumbnail_candidate(self, path: Path, pixmap: QPixmap, processing_message: str = "") -> None:
        self.last_thumbnail_candidate = path
        validation = validate_thumbnail_file(path)
        preview = pixmap.scaled(self.thumbnail_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        preview.setDevicePixelRatio(1.0)
        self.thumbnail_preview.setPixmap(preview)
        self.thumbnail_preview.set_candidate(path, pixmap)
        details = f"{path.name}\n{pixmap.width()}×{pixmap.height()} · {validation.size_bytes:,} bytes · {validation.mime_type}"
        if processing_message:
            details = f"{details}\n{processing_message}"
        self.thumbnail_candidate_label.setText(
            details
        )
        self.upload_thumbnail_btn.setEnabled(validation.can_upload)
        self.open_thumbnail_preview_btn.setEnabled(bool(self.current_video))
        self.open_watch_page_btn.setEnabled(bool(self.current_video))

    def _upload_last_thumbnail_candidate(self) -> None:
        if not self.last_thumbnail_candidate:
            QMessageBox.information(self, "썸네일 후보 없음", "먼저 현재 화면을 썸네일 후보로 캡처하세요.")
            return
        self.upload_thumbnail(self.last_thumbnail_candidate)

    def _open_thumbnail_web_preview(self) -> None:
        if not self.current_video:
            return
        QDesktopServices.openUrl(QUrl(public_thumbnail_url(self.current_video.video_id, cache_bust=True)))

    def _open_video_watch_page(self) -> None:
        if not self.current_video:
            return
        QDesktopServices.openUrl(QUrl(public_watch_url(self.current_video.video_id)))

    def upload_thumbnail(self, path: Path) -> None:
        if not self.current_video:
            return
        if not self.youtube:
            try:
                service = self.oauth.build_youtube_service(write_access=True)
                self.youtube = YouTubeApiClient(service)
            except Exception as exc:
                QMessageBox.critical(self, "권한 요청 실패", f"썸네일 업로드 권한을 얻지 못했습니다.\n\n{exc}")
                return
        try:
            self.youtube.upload_thumbnail(self.current_video.video_id, path)
            self.open_thumbnail_preview_btn.setEnabled(True)
            self.open_watch_page_btn.setEnabled(True)
            QMessageBox.information(
                self,
                "업로드 완료",
                "썸네일을 YouTube에 업로드했습니다.\n\n"
                "YouTube 웹 반영은 지연될 수 있습니다. 아래의 '웹 썸네일 확인' 또는 '영상 페이지 열기'로 실제 반영 상태를 확인하세요.",
            )
        except YouTubeApiError as exc:
            QMessageBox.warning(self, "업로드 실패", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "업로드 실패", f"썸네일 업로드 중 오류가 발생했습니다.\n\n{exc}")

    def apply_selected_draft(self) -> None:
        if not self.current_video or not self.current_description_draft:
            QMessageBox.information(self, "적용 대상 없음", "먼저 검수 완료된 영상을 선택하세요.")
            return
        draft = self._draft_from_ui(self.current_description_draft.status)
        if draft:
            self.db.save_description_draft(draft, preserve_reviewed=False)
            self.current_description_draft = self.db.get_description_draft(draft.video_id)
        if not self.current_description_draft or self.current_description_draft.status != DRAFT_STATUS_REVIEWED:
            QMessageBox.warning(self, "검수 필요", "선택 적용은 검수 완료 상태의 영상만 가능합니다.")
            return
        self._apply_pairs([(self.current_video, self.current_description_draft)])

    def apply_reviewed_drafts(self) -> None:
        pairs = self.db.list_apply_ready_drafts()
        if not pairs:
            QMessageBox.information(self, "적용 대상 없음", "검수 완료이면서 변경된 초안이 없습니다.")
            return
        answer = QMessageBox.question(
            self,
            "일괄 적용 확인",
            f"검수 완료된 변경분 {len(pairs)}개를 YouTube에 적용합니다. 계속할까요?",
        )
        if answer != QMessageBox.Yes:
            return
        self._apply_pairs(pairs)

    def _apply_pairs(self, pairs: list[tuple[VideoSummary, DescriptionDraftRecord]]) -> None:
        try:
            if not self.youtube:
                service = self.oauth.build_youtube_service(write_access=True)
                self.youtube = YouTubeApiClient(service)
            success = 0
            failed = 0
            for video, draft in pairs:
                try:
                    self.db.save_snapshot(video)
                    self.youtube.update_video_snippet(video.video_id, video.title, draft.rendered_description, list(video.tags))
                    updated = VideoSummary(
                        video_id=video.video_id,
                        title=video.title,
                        description=draft.rendered_description,
                        tags=video.tags,
                        thumbnail_url=video.thumbnail_url,
                        duration=video.duration,
                        privacy_status=video.privacy_status,
                        published_at=video.published_at,
                        category_id=video.category_id,
                        width_pixels=video.width_pixels,
                        height_pixels=video.height_pixels,
                        display_aspect_ratio=video.display_aspect_ratio,
                    )
                    self.db.save_videos([updated])
                    self.db.mark_draft_status(video.video_id, DRAFT_STATUS_APPLIED)
                    success += 1
                except Exception as exc:  # 개별 실패는 기록 후 계속한다.
                    self.db.mark_draft_status(video.video_id, DRAFT_STATUS_ERROR, str(exc))
                    failed += 1
            self._load_cached_videos()
            QMessageBox.information(self, "적용 완료", f"성공 {success}개, 실패 {failed}개")
        except Exception as exc:
            QMessageBox.critical(self, "적용 실패", f"YouTube 업데이트 준비 중 오류가 발생했습니다.\n\n{exc}")

    def open_character_master_window(self) -> None:
        if self._character_master_window is None:
            self._character_master_window = CharacterMasterWindow(self.db, self)
        self._character_master_window.show()
        self._character_master_window.raise_()
        self._character_master_window.activateWindow()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._character_master_window is not None:
            self._character_master_window.close()
        if hasattr(self, "local_upload_widget"):
            self.local_upload_widget.persist_session_on_close()
        self.db.close()
        super().closeEvent(event)


def candidate_to_record(candidate) -> DescriptionDraftRecord:

    return candidate_to_draft_record(candidate)


def section_to_json(section: DescriptionSection) -> dict[str, object]:
    return {
        "stage_number": section.stage_number,
        "boss_name": section.boss_name,
        "party_composition": section.party_composition,
        "party": [
            {
                "character": member.character,
                "m_level": member.m_level,
                "equip": member.equip,
                "raw_name": member.raw_name,
                "canonical_name": member.canonical_name,
                "character_rank": member.character_rank,
                "character_rank_value": member.character_rank_value,
                "equipment_type": member.equipment_type,
                "equipment_rank": member.equipment_rank,
                "equipment_rank_value": member.equipment_rank_value,
                "raw_status": member.raw_status,
                "parse_warnings": list(member.parse_warnings),
            }
            for member in section.party
        ],
    }

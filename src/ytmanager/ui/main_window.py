from __future__ import annotations

import difflib
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from ytmanager.description import load_template, render_description
from ytmanager.models import TimestampEntry, VideoDraft, VideoSummary
from ytmanager.oauth import OAuthManager, OAuthSetupError
from ytmanager.paths import user_cache_dir
from ytmanager.rules import load_rule_mappings, top_tags_for_title
from ytmanager.storage import AppDatabase
from ytmanager.thumbnail import validate_thumbnail_file
from ytmanager.youtube_api import YouTubeApiClient, YouTubeApiError

PLAYER_HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <style>
    html, body { margin: 0; height: 100%; background: #111; color: #eee; font-family: sans-serif; }
    #player { width: 100%; height: 100%; min-height: 320px; }
    #empty { display: flex; align-items: center; justify-content: center; height: 100%; color: #aaa; }
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
      if (pendingVideoId) {
        loadVideo(pendingVideoId);
      }
    }
    function loadVideo(videoId) {
      pendingVideoId = videoId;
      if (!window.YT || !window.YT.Player) { return; }
      if (player) {
        player.loadVideoById(videoId);
      } else {
        player = new YT.Player('player', {
          width: '100%',
          height: '100%',
          videoId: videoId,
          playerVars: { 'playsinline': 1, 'origin': window.location.origin },
          events: {}
        });
      }
    }
    function getCurrentTimeSafe() {
      if (!player || !player.getCurrentTime) { return 0; }
      return player.getCurrentTime();
    }
    function seekToSafe(seconds) {
      if (player && player.seekTo) { player.seekTo(seconds, true); }
    }
    loadApi();
  </script>
</body>
</html>
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("YTmanager - YouTube 영상 관리")
        self.resize(1400, 850)
        self.db = AppDatabase()
        self.oauth = OAuthManager()
        self.youtube: Optional[YouTubeApiClient] = None
        self.current_video: Optional[VideoSummary] = None
        self.current_draft: Optional[VideoDraft] = None
        self.timestamps: list[TimestampEntry] = []
        self.template_text = load_template()
        self.rule_mappings = load_rule_mappings()

        self._build_ui()
        self._load_cached_videos()

    def _build_ui(self) -> None:
        toolbar = QToolBar("주요 작업")
        self.addToolBar(toolbar)
        login_btn = QPushButton("Google 로그인")
        login_btn.clicked.connect(self.login)
        sync_btn = QPushButton("영상 목록 동기화")
        sync_btn.clicked.connect(self.sync_videos)
        apply_btn = QPushButton("YouTube에 적용")
        apply_btn.clicked.connect(self.apply_changes)
        toolbar.addWidget(login_btn)
        toolbar.addWidget(sync_btn)
        toolbar.addWidget(apply_btn)

        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("업로드 영상"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("제목 검색")
        self.search.textChanged.connect(self._filter_video_list)
        left_layout.addWidget(self.search)
        self.video_list = QListWidget()
        self.video_list.currentItemChanged.connect(self._on_video_selected)
        left_layout.addWidget(self.video_list)
        splitter.addWidget(left)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.addWidget(QLabel("재생 및 시점 지정"))
        self.player = QWebEngineView()
        self.player.setHtml(PLAYER_HTML, QUrl("https://ytmanager.local/"))
        center_layout.addWidget(self.player, stretch=1)
        player_buttons = QHBoxLayout()
        timestamp_btn = QPushButton("현재 시점을 타임스탬프로 추가")
        timestamp_btn.clicked.connect(self.add_current_timestamp)
        capture_btn = QPushButton("현재 화면을 썸네일 후보로 캡처")
        capture_btn.clicked.connect(self.capture_thumbnail_candidate)
        player_buttons.addWidget(timestamp_btn)
        player_buttons.addWidget(capture_btn)
        center_layout.addLayout(player_buttons)
        self.timestamp_editor = QPlainTextEdit()
        self.timestamp_editor.setPlaceholderText("타임스탬프가 여기에 누적됩니다. 예: 01:23 - 보스전 시작")
        self.timestamp_editor.textChanged.connect(self.refresh_description_preview)
        center_layout.addWidget(self.timestamp_editor)
        splitter.addWidget(center)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("제목"))
        self.title_editor = QLineEdit()
        self.title_editor.textChanged.connect(self.refresh_description_preview)
        right_layout.addWidget(self.title_editor)
        right_layout.addWidget(QLabel("구조화 필드"))
        self.fields_editor = QPlainTextEdit()
        self.fields_editor.setPlaceholderText("game_version=2.7\ngame_content_name=위험한 강습전\ngame_content_season_in_current_version=1차\nnotes=자유 메모")
        self.fields_editor.textChanged.connect(self.refresh_description_preview)
        right_layout.addWidget(self.fields_editor)
        right_layout.addWidget(QLabel("설명 미리보기"))
        self.description_editor = QPlainTextEdit()
        self.description_editor.textChanged.connect(self.refresh_diff)
        right_layout.addWidget(self.description_editor, stretch=1)
        right_layout.addWidget(QLabel("변경사항 diff"))
        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        right_layout.addWidget(self.diff_view, stretch=1)
        splitter.addWidget(right)
        splitter.setSizes([300, 550, 550])

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("준비됨")

    def login(self) -> None:
        try:
            service = self.oauth.build_youtube_service(write_access=False)
            self.youtube = YouTubeApiClient(service)
            self.statusBar().showMessage("Google 로그인 완료")
            QMessageBox.information(self, "로그인 완료", "Google 계정 연동이 완료되었습니다.")
        except OAuthSetupError as exc:
            QMessageBox.warning(self, "로그인 설정 필요", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "로그인 실패", f"Google 로그인 중 오류가 발생했습니다.\n\n{exc}")

    def sync_videos(self) -> None:
        if not self.youtube:
            self.login()
            if not self.youtube:
                return
        try:
            videos = self.youtube.list_uploaded_videos(limit=50)
            self.db.save_videos(videos)
            self._populate_videos(videos)
            self.statusBar().showMessage(f"영상 {len(videos)}개를 동기화했습니다.")
        except Exception as exc:
            QMessageBox.critical(self, "동기화 실패", f"영상 목록을 가져오지 못했습니다.\n\n{exc}")

    def _load_cached_videos(self) -> None:
        self._populate_videos(self.db.list_videos())

    def _populate_videos(self, videos: list[VideoSummary]) -> None:
        self.video_list.clear()
        for video in videos:
            item = QListWidgetItem(video.title)
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
        self.timestamps = []
        self.title_editor.setText(video.title)
        self.description_editor.setPlainText(video.description)
        self.timestamp_editor.setPlainText("")
        self.fields_editor.setPlainText("")
        self.player.page().runJavaScript(f"loadVideo({video.video_id!r});")
        self.refresh_diff()
        self.statusBar().showMessage(f"선택됨: {video.title}")

    def _parse_fields(self) -> dict[str, str]:
        fields: dict[str, str] = {}
        for line in self.fields_editor.toPlainText().splitlines():
            if not line.strip() or "=" not in line:
                continue
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
        return fields

    def _parse_timestamp_editor(self) -> list[TimestampEntry]:
        entries: list[TimestampEntry] = []
        for line in self.timestamp_editor.toPlainText().splitlines():
            if not line.strip():
                continue
            stamp, _, label = line.partition("-")
            from ytmanager.timestamps import parse_timestamp
            try:
                seconds = parse_timestamp(stamp.strip())
            except ValueError:
                continue
            entries.append(TimestampEntry(seconds, label.strip()))
        return entries

    def refresh_description_preview(self) -> None:
        if not self.current_video:
            return
        title = self.title_editor.text()
        tags = top_tags_for_title(title, self.rule_mappings)
        fields = self._parse_fields()
        timestamps = self._parse_timestamp_editor()
        description = render_description(self.template_text, fields, tags, timestamps)
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
        from ytmanager.timestamps import format_timestamp
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
        target = user_cache_dir() / f"thumbnail-{self.current_video.video_id}.png"
        pixmap: QPixmap = self.player.grab()
        if not pixmap.save(str(target), "PNG"):
            QMessageBox.warning(self, "캡처 실패", "현재 재생 화면을 이미지로 저장하지 못했습니다.")
            return
        validation = validate_thumbnail_file(target)
        if not validation.can_upload:
            QMessageBox.warning(self, "썸네일 검증 실패", validation.message)
            return
        answer = QMessageBox.question(
            self,
            "썸네일 후보 생성",
            f"썸네일 후보를 저장했습니다.\n{target}\n\n이 이미지는 환경에 따라 검은 화면일 수 있으니 확인 후 업로드하세요. 지금 업로드할까요?",
        )
        if answer == QMessageBox.Yes:
            self.upload_thumbnail(target)

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
            QMessageBox.information(self, "업로드 완료", "썸네일을 YouTube에 업로드했습니다.")
        except YouTubeApiError as exc:
            QMessageBox.warning(self, "업로드 실패", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "업로드 실패", f"썸네일 업로드 중 오류가 발생했습니다.\n\n{exc}")

    def apply_changes(self) -> None:
        if not self.current_video:
            QMessageBox.information(self, "영상 선택 필요", "먼저 영상을 선택하세요.")
            return
        title = self.title_editor.text().strip()
        description = self.description_editor.toPlainText().strip()
        # 현재 MVP의 자동 태그는 설명 상단 해시태그를 뜻한다.
        # YouTube snippet.tags는 별도 관리 UI가 생기기 전까지 기존 값을 보존한다.
        tags = list(self.current_video.tags)
        if not title:
            QMessageBox.warning(self, "제목 필요", "제목은 비워둘 수 없습니다.")
            return
        answer = QMessageBox.question(
            self,
            "YouTube에 적용",
            "현재 미리보기의 제목/설명/태그를 YouTube에 적용합니다. 적용 전 기존 값은 로컬 스냅샷으로 저장됩니다. 계속할까요?",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            if not self.youtube:
                service = self.oauth.build_youtube_service(write_access=True)
                self.youtube = YouTubeApiClient(service)
            self.db.save_snapshot(self.current_video)
            self.youtube.update_video_snippet(self.current_video.video_id, title, description, tags)
            updated = VideoSummary(
                video_id=self.current_video.video_id,
                title=title,
                description=description,
                tags=tuple(tags),
                thumbnail_url=self.current_video.thumbnail_url,
                duration=self.current_video.duration,
                privacy_status=self.current_video.privacy_status,
                published_at=self.current_video.published_at,
                category_id=self.current_video.category_id,
            )
            self.db.save_videos([updated])
            self.current_video = updated
            QMessageBox.information(self, "적용 완료", "YouTube 메타데이터를 업데이트했습니다.")
            self._load_cached_videos()
        except Exception as exc:
            QMessageBox.critical(self, "적용 실패", f"YouTube 업데이트 중 오류가 발생했습니다.\n\n{exc}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.db.close()
        super().closeEvent(event)

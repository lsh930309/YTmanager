from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from ytmanager.models import VideoSummary
from ytmanager.thumbnail import validate_thumbnail_file

YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_MANAGE_SCOPE = "https://www.googleapis.com/auth/youtube"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
DEFAULT_READ_SCOPES = [YOUTUBE_READONLY_SCOPE]
DEFAULT_WRITE_SCOPES = [YOUTUBE_MANAGE_SCOPE, YOUTUBE_UPLOAD_SCOPE]
VIDEO_LIST_PARTS = "snippet,contentDetails,status"
VIDEO_LIST_PARTS_WITH_FILE_DETAILS = f"{VIDEO_LIST_PARTS},fileDetails"


class YouTubeApiError(RuntimeError):
    """YouTube API 호출 실패."""


class YouTubeApiClient:
    def __init__(self, service: Any) -> None:
        self.service = service

    def get_uploads_playlist_id(self) -> str:
        response = self.service.channels().list(part="contentDetails", mine=True, maxResults=1).execute()
        items = response.get("items", [])
        if not items:
            raise YouTubeApiError("로그인한 계정에서 YouTube 채널을 찾을 수 없습니다.")
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def list_uploaded_video_ids(self, page_token: Optional[str] = None, max_results: int = 50) -> tuple[list[str], Optional[str]]:
        playlist_id = self.get_uploads_playlist_id()
        request = self.service.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=max_results,
            pageToken=page_token,
        )
        response = request.execute()
        ids = [item["contentDetails"]["videoId"] for item in response.get("items", [])]
        return ids, response.get("nextPageToken")

    def fetch_videos(self, video_ids: list[str]) -> list[VideoSummary]:
        if not video_ids:
            return []
        try:
            response = self._list_video_resources(video_ids, VIDEO_LIST_PARTS_WITH_FILE_DETAILS)
        except Exception as exc:
            if not self._is_file_details_unavailable(exc):
                raise
            response = self._list_video_resources(video_ids, VIDEO_LIST_PARTS)
        return [VideoSummary.from_youtube_resource(item) for item in response.get("items", [])]

    def _list_video_resources(self, video_ids: list[str], part: str) -> Mapping[str, Any]:
        return self.service.videos().list(
            part=part,
            id=",".join(video_ids),
            maxResults=min(50, len(video_ids)),
        ).execute()

    @staticmethod
    def _is_file_details_unavailable(exc: Exception) -> bool:
        """fileDetails 권한/가용성 문제만 기본 part 조회로 fallback한다."""
        try:
            from googleapiclient.errors import HttpError
        except ImportError:
            return False
        if not isinstance(exc, HttpError):
            return False
        status = getattr(getattr(exc, "resp", None), "status", None)
        content = getattr(exc, "content", b"")
        if isinstance(content, bytes):
            text = content.decode("utf-8", errors="ignore")
        else:
            text = str(content)
        lowered = text.casefold()
        if any(reason in lowered for reason in ("quotaexceeded", "dailylimitexceeded", "ratelimitexceeded")):
            return False
        if status == 400:
            return "filedetails" in lowered or "invalidpart" in lowered
        if status == 403:
            return any(reason in lowered for reason in ("filedetails", "file details", "file", "processing", "forbidden"))
        return False

    def list_uploaded_videos(self, limit: int = 50) -> list[VideoSummary]:
        all_ids: list[str] = []
        token: Optional[str] = None
        while len(all_ids) < limit:
            ids, token = self.list_uploaded_video_ids(token, max_results=min(50, limit - len(all_ids)))
            all_ids.extend(ids)
            if not token or not ids:
                break
        videos: list[VideoSummary] = []
        for start in range(0, len(all_ids), 50):
            videos.extend(self.fetch_videos(all_ids[start:start + 50]))
        return videos

    def get_video_resource(self, video_id: str) -> Mapping[str, Any]:
        response = self.service.videos().list(part="snippet,status", id=video_id).execute()
        items = response.get("items", [])
        if not items:
            raise YouTubeApiError("대상 영상을 찾을 수 없습니다.")
        return items[0]

    @staticmethod
    def build_snippet_update_payload(
        existing_resource: Mapping[str, Any],
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        snippet = dict(existing_resource.get("snippet", {}) or {})
        video_id = str(existing_resource.get("id", ""))
        if not video_id:
            raise ValueError("영상 ID가 필요합니다.")
        if title is not None:
            snippet["title"] = title
        if description is not None:
            snippet["description"] = description
        if tags is not None:
            snippet["tags"] = tags
        if not snippet.get("title"):
            raise ValueError("영상 제목은 비어 있을 수 없습니다.")
        snippet.setdefault("categoryId", "22")
        return {"id": video_id, "snippet": snippet}

    def update_video_snippet(self, video_id: str, title: str, description: str, tags: list[str]) -> Mapping[str, Any]:
        existing = self.get_video_resource(video_id)
        body = self.build_snippet_update_payload(existing, title=title, description=description, tags=tags)
        return self.service.videos().update(part="snippet", body=body).execute()

    def upload_thumbnail(self, video_id: str, image_path: Path) -> Mapping[str, Any]:
        validation = validate_thumbnail_file(image_path)
        if not validation.can_upload:
            raise YouTubeApiError(validation.message)
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise YouTubeApiError("google-api-python-client가 설치되어 있지 않습니다.") from exc
        media = MediaFileUpload(str(image_path), mimetype=validation.mime_type, resumable=False)
        return self.service.thumbnails().set(videoId=video_id, media_body=media).execute()

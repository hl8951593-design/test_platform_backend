import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.api.v1.routers import media
from app.services.media_service import MediaService
from app.services.object_storage_service import ObjectStorageService


def _methods_by_path(router) -> dict[str, set[str]]:
    methods: dict[str, set[str]] = {}
    for route in router.routes:
        if hasattr(route, "methods"):
            methods.setdefault(route.path, set()).update(route.methods or ())
    return methods


class MediaRouteTests(unittest.TestCase):
    def test_media_routes_are_registered(self):
        methods = _methods_by_path(media.router)

        self.assertEqual({"POST"}, methods["/images"])
        self.assertEqual({"GET"}, methods["/{media_id}/url"])
        self.assertEqual({"DELETE"}, methods["/{media_id}"])


class MediaServiceTests(unittest.TestCase):
    def setUp(self):
        self.storage = MagicMock()
        self.storage.upload.return_value = "etag-1"
        self.storage.presigned_get_url.return_value = "http://minio/signed"
        self.service = MediaService(MagicMock(), storage=self.storage)
        self.service.permission_service = MagicMock()
        self.service.repository = MagicMock()
        self.user = SimpleNamespace(id=7)

    def test_upload_image_validates_content_and_persists_object_metadata(self):
        upload = SimpleNamespace(
            filename="screenshot.png",
            content_type="image/png",
            file=io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"content"),
        )
        self.service.repository.create.return_value = SimpleNamespace(id=12)

        result = self.service.upload_image(project_id=3, upload=upload, current_user=self.user)

        self.assertEqual(12, result.id)
        upload_kwargs = self.storage.upload.call_args.kwargs
        self.assertEqual("image/png", upload_kwargs["content_type"])
        self.assertTrue(upload_kwargs["object_key"].startswith("projects/3/defects/"))
        create_kwargs = self.service.repository.create.call_args.kwargs
        self.assertEqual("screenshot.png", create_kwargs["original_filename"])
        self.assertEqual(len(b"\x89PNG\r\n\x1a\n" + b"content"), create_kwargs["size_bytes"])

    def test_upload_rejects_spoofed_image(self):
        upload = SimpleNamespace(
            filename="payload.png",
            content_type="image/png",
            file=io.BytesIO(b"not-a-png"),
        )

        with self.assertRaises(HTTPException) as context:
            self.service.upload_image(project_id=3, upload=upload, current_user=self.user)

        self.assertEqual(400, context.exception.status_code)
        self.storage.upload.assert_not_called()


    def test_attachment_cannot_cross_projects(self):
        self.service.repository.list_by_ids.return_value = [
            SimpleNamespace(id=2, project_id=99, owner_id=7, defect_id=None)
        ]

        with self.assertRaises(HTTPException) as context:
            self.service.resolve_pending_attachments(
                project_id=3,
                media_ids=[2],
                current_user=self.user,
            )

        self.assertEqual(400, context.exception.status_code)


class ObjectStorageServiceTests(unittest.TestCase):
    def test_upload_uses_put_response_etag_without_head_request(self):
        client = MagicMock()
        client.put_object.return_value = {"ETag": '"etag-1"'}
        service = ObjectStorageService()
        service.__dict__["client"] = client

        etag = service.upload(
            fileobj=io.BytesIO(b"image"),
            object_key="projects/1/defects/image.png",
            content_type="image/png",
        )

        self.assertEqual("etag-1", etag)
        client.put_object.assert_called_once()
        client.head_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()

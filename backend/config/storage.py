from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


def _private_base():
    if getattr(settings, "STORAGE_BACKEND", "local") == "s3":
        from storages.backends.s3 import S3Storage

        return S3Storage
    return FileSystemStorage


@deconstructible(path="config.storage.PrivateStorage")
class PrivateStorage(_private_base()):
    """Storage for private files (documents, signed copies, attachments).

    * local: files under PRIVATE_MEDIA_ROOT, outside the web root.
    * s3:    a separate, fully private bucket (Block Public Access, SSE). Files
             are streamed by Django after permission checks; no public URLs.
    """

    def __init__(self, **kwargs):
        if getattr(settings, "STORAGE_BACKEND", "local") == "s3":
            kwargs.setdefault("bucket_name", settings.AWS_PRIVATE_BUCKET_NAME)
            kwargs.setdefault("location", "private")
            kwargs.setdefault("default_acl", None)
            kwargs.setdefault("querystring_auth", True)
            kwargs.setdefault("querystring_expire", 300)
            kwargs.setdefault("custom_domain", None)
        else:
            kwargs.setdefault("location", settings.PRIVATE_MEDIA_ROOT)
            kwargs.setdefault("base_url", None)
        super().__init__(**kwargs)

    def deconstruct(self):
        # Keep migrations independent of the environment and machine paths.
        return ("config.storage.PrivateStorage", [], {})


private_storage = PrivateStorage()

"""pytest-django configuration — point to the project settings module."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fk_cesis_mms.settings")


def pytest_configure(config):
    import django

    django.setup()

    # Patch Django 6.0 test client file upload regression.
    # Client.post passes `files` via **extra but RequestFactory.post
    # (the parent class) ignores it — files never get encoded into
    # the multipart request body.  Merge files into data before the
    # parent processes the request.
    from django.test.client import RequestFactory, MULTIPART_CONTENT

    _original_rf_post = RequestFactory.post

    def _patched_rf_post(
        self,
        path,
        data=None,
        content_type=MULTIPART_CONTENT,
        secure=False,
        *,
        headers=None,
        query_params=None,
        **extra,
    ):
        files = extra.pop("files", None)
        if data is None:
            data = {}
        if files and isinstance(data, dict):
            data = dict(data)
            data.update(files)
        post_data = self._encode_data(data, content_type)
        return self.generic(
            "POST",
            path,
            post_data,
            content_type,
            secure=secure,
            headers=headers,
            query_params=query_params,
            **extra,
        )

    RequestFactory.post = _patched_rf_post

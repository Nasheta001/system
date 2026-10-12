import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def safe_exception_handler(exc, context):
    """DRF handler that converts common Django errors into clean API responses
    and never leaks stack traces or internal details to clients."""
    response = exception_handler(exc, context)
    if response is not None:
        return response
    if isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "error_dict") else {"detail": exc.messages}
        return Response(detail, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, ProtectedError):
        return Response(
            {"detail": "This record is linked to financial or tenancy history and cannot be deleted. Archive it instead."},
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, IntegrityError):
        logger.warning("Integrity error: %s", exc)
        return Response(
            {"detail": "The change conflicts with existing records. Refresh and try again."},
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, DjangoPermissionDenied):
        return Response({"detail": "You do not have permission to perform this action."}, status=403)
    logger.exception("Unhandled API error")
    return Response({"detail": "An unexpected error occurred."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

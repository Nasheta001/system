from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("documents", views.DocumentViewSet, basename="document")
router.register("signature-requests", views.SignatureRequestViewSet, basename="signature-request")
router.register("portal/documents", views.PortalDocumentViewSet, basename="portal-document")

urlpatterns = [
    path("portal/signature-requests/<int:pk>/upload/", views.PortalSignatureUploadView.as_view()),
] + router.urls

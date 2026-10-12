from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("announcements", views.AnnouncementViewSet, basename="announcement")
router.register("notification-templates", views.TemplateViewSet, basename="notification-template")
router.register("notification-log", views.NotificationLogViewSet, basename="notification-log")
router.register("portal/announcements", views.PortalAnnouncementViewSet, basename="portal-announcement")

urlpatterns = [
    path("announcement-attachments/<int:pk>/download/", views.AttachmentDownloadView.as_view()),
    path("notification-channels/", views.ChannelStatusView.as_view()),
    path("my-notifications/", views.MyNotificationsView.as_view()),
] + router.urls

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("viewing-requests", views.ViewingRequestViewSet, basename="viewing-request")
router.register("applications", views.ApplicationViewSet, basename="application")
router.register("reservations", views.ReservationViewSet, basename="reservation")

urlpatterns = [
    path("public/viewing-requests/", views.PublicViewingRequestView.as_view()),
    path("public/applications/", views.PublicApplicationView.as_view()),
    path("public/applications/status/", views.PublicApplicationStatusView.as_view()),
] + router.urls

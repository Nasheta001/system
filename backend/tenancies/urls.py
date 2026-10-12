from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("tenants", views.TenantViewSet, basename="tenant")
router.register("tenancies", views.TenancyViewSet, basename="tenancy")

urlpatterns = [
    path("portal/profile/", views.PortalProfileView.as_view()),
    path("portal/dashboard/", views.PortalDashboardView.as_view()),
] + router.urls

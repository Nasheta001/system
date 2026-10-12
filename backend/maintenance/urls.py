from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("maintenance", views.MaintenanceViewSet, basename="maintenance")
router.register("portal/maintenance", views.PortalMaintenanceViewSet, basename="portal-maintenance")

urlpatterns = router.urls

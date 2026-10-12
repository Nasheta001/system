from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("properties", views.PropertyViewSet, basename="property")
router.register("buildings", views.BuildingViewSet, basename="building")
router.register("units", views.UnitViewSet, basename="unit")
router.register("unit-types", views.UnitTypeViewSet, basename="unit-type")
router.register("amenities", views.AmenityViewSet, basename="amenity")
router.register("property-photos", views.PhotoViewSet, basename="property-photo")
router.register("ownership-records", views.OwnershipViewSet, basename="ownership")

urlpatterns = [
    path("public/properties/", views.PublicPropertyListView.as_view()),
    path("public/properties/<slug:slug>/", views.PublicPropertyDetailView.as_view()),
    path("public/filters/", views.PublicFiltersView.as_view()),
] + router.urls

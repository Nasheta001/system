from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("staff", views.StaffViewSet, basename="staff")
router.register("audit-logs", views.AuditLogViewSet, basename="audit-log")
router.register("staff-invitations", views.StaffInvitationViewSet, basename="staff-invitation")

urlpatterns = [
    path("auth/setup/", views.InitialSetupView.as_view()),
    path("auth/invitations/check/", views.InvitationCheckView.as_view()),
    path("auth/invitations/accept/", views.InvitationAcceptView.as_view()),
    path("auth/csrf/", views.CsrfView.as_view()),
    path("auth/login/", views.LoginView.as_view()),
    path("auth/logout/", views.LogoutView.as_view()),
    path("auth/me/", views.MeView.as_view()),
    path("auth/password/change/", views.PasswordChangeView.as_view()),
    path("auth/password/reset/", views.PasswordResetRequestView.as_view()),
    path("auth/password/reset/confirm/", views.PasswordResetConfirmView.as_view()),
    path("staff-options/", views.StaffOptionsView.as_view()),
    path("settings/company/", views.CompanySettingsView.as_view()),
    path("public/company/", views.PublicCompanyView.as_view()),
] + router.urls

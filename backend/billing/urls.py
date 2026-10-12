from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("payments", views.PaymentViewSet, basename="payment")
router.register("charges", views.ChargeViewSet, basename="charge")
router.register("mpesa-transactions", views.MpesaTransactionViewSet, basename="mpesa-transaction")
router.register("reminder-schedules", views.ReminderScheduleViewSet, basename="reminder-schedule")
router.register("follow-ups", views.FollowUpViewSet, basename="follow-up")

urlpatterns = [
    path("payments/mpesa/callback/<str:token>/", views.MpesaCallbackView.as_view()),
    path("payment-config/", views.PaymentConfigView.as_view()),
    path("tenancies/<int:pk>/ledger/", views.TenancyLedgerView.as_view()),
    path("portal/account/", views.PortalAccountView.as_view()),
    path("portal/payments/mpesa/", views.PortalStkPushView.as_view()),
    path("portal/payments/phone-report/", views.PortalPhonePaymentReportView.as_view()),
    path("portal/payments/mpesa/<int:pk>/", views.PortalTransactionView.as_view()),
    path("portal/payments/mpesa/<int:pk>/simulate/", views.PortalSimulateView.as_view()),
    path("portal/payments/<int:pk>/receipt/", views.PortalReceiptView.as_view()),
    path("portal/tenancies/<int:pk>/statement/", views.PortalStatementView.as_view()),
] + router.urls

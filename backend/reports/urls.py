from django.urls import path

from . import views
from .system import RunJobsView

urlpatterns = [
    path("dashboard/", views.DashboardView.as_view()),
    path("reports/", views.ReportListView.as_view()),
    path("reports/<slug:name>/", views.ReportView.as_view()),
    path("system/run-jobs/", RunJobsView.as_view()),
]

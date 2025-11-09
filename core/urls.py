from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.login_view, name="login"),
    path("auth/ion/", views.oauth_start, name="oauth_start"),
    path("complete/ion/", views.oauth_callback, name="oauth_callback"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
]

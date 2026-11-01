from django.urls import path
from . import views

app_name = "node"

urlpatterns = [
    path("store/<uuid:blob_id>/", views.StoreView.as_view()),
    path("health/", views.HealthView.as_view()),
]
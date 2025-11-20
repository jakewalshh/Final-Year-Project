from django.urls import path
from .views import sample_plan

urlpatterns = [
    path("sample-plan/", sample_plan, name="sample-plan"),
]

from django.urls import path
from .views import sample_plan, plan_meals

urlpatterns = [
    path("sample-plan/", sample_plan, name="sample-plan"),
    path("plan-meals/", plan_meals, name="plan-meals"),
]

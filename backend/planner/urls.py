from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    GenerateMealPlanView,
    IngredientPricingReportView,
    LoginView,
    MealPlanDetailView,
    MealPlanListView,
    MeView,
    PreferenceView,
    RateMealView,
    RegisterView,
    ShoppingListView,
    SwapMealView,
    TagListView,
)

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("auth/me/", MeView.as_view(), name="auth-me"),

    path("preferences/", PreferenceView.as_view(), name="preferences"),
    path("tags/", TagListView.as_view(), name="tag-list"),
    path("reports/ingredient-pricing/", IngredientPricingReportView.as_view(), name="ingredient-pricing-report"),

    path("meal-plans/generate/", GenerateMealPlanView.as_view(), name="meal-plan-generate"),
    path("meal-plans/", MealPlanListView.as_view(), name="meal-plan-list"),
    path("meal-plans/<int:plan_id>/", MealPlanDetailView.as_view(), name="meal-plan-detail"),
    path("meal-plans/<int:plan_id>/swap/", SwapMealView.as_view(), name="meal-plan-swap"),
    path("meal-plans/<int:plan_id>/rate/", RateMealView.as_view(), name="meal-plan-rate"),
    path("meal-plans/<int:plan_id>/shopping-list/", ShoppingListView.as_view(), name="shopping-list"),
]

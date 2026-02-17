from django.urls import path
from .views import plan_meals, recipe_detail, sample_plan, search_recipes

urlpatterns = [
    path("sample-plan/", sample_plan, name="sample-plan"),
    path("plan-meals/", plan_meals, name="plan-meals"),
    path("recipes/search/", search_recipes, name="search-recipes"),
    path("recipes/<int:recipe_id>/", recipe_detail, name="recipe-detail"),
]

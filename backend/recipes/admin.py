from django.contrib import admin

from .models import (
    Ingredient,
    Recipe,
    RecipeIngredient,
    RecipeStep,
    RecipeTag,
    Tag,
)


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("id", "external_id", "name", "minutes", "submitted_date")
    search_fields = ("name", "external_id")
    list_filter = ("submitted_date",)


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(RecipeIngredient)
class RecipeIngredientAdmin(admin.ModelAdmin):
    list_display = ("recipe_id", "ingredient_id", "position")
    search_fields = ("recipe__name", "ingredient__name")


@admin.register(RecipeStep)
class RecipeStepAdmin(admin.ModelAdmin):
    list_display = ("recipe_id", "step_number")
    search_fields = ("recipe__name", "instruction")


@admin.register(RecipeTag)
class RecipeTagAdmin(admin.ModelAdmin):
    list_display = ("recipe_id", "tag_id")
    search_fields = ("recipe__name", "tag__name")

from django.contrib import admin

from .models import MealPlan, MealPlanItem, ShoppingList, UserPreference


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "max_minutes_default", "updated_at")
    search_fields = ("user__email", "user__username")


class MealPlanItemInline(admin.TabularInline):
    model = MealPlanItem
    extra = 0


@admin.register(MealPlan)
class MealPlanAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "created_at")
    inlines = [MealPlanItemInline]
    search_fields = ("title", "user__email", "user__username")


@admin.register(ShoppingList)
class ShoppingListAdmin(admin.ModelAdmin):
    list_display = ("meal_plan", "created_at")

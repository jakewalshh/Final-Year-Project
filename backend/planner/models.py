from django.conf import settings
from django.db import models


class UserPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    excluded_ingredients = models.JSONField(default=list, blank=True)
    preferred_tags = models.JSONField(default=list, blank=True)
    excluded_tags = models.JSONField(default=list, blank=True)
    max_minutes_default = models.PositiveIntegerField(null=True, blank=True)
    nutrition_defaults = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"prefs:{self.user_id}"


class MealPlan(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="meal_plans",
    )
    title = models.CharField(max_length=200)
    source_prompt = models.TextField(blank=True, default="")
    parsed_query = models.JSONField(default=dict)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"plan:{self.id}:{self.user_id}"


class MealPlanItem(models.Model):
    meal_plan = models.ForeignKey(
        MealPlan,
        on_delete=models.CASCADE,
        related_name="items",
    )
    position = models.PositiveIntegerField()
    recipe = models.ForeignKey(
        "recipes.Recipe",
        on_delete=models.CASCADE,
        related_name="plan_items",
    )
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    rated_at = models.DateTimeField(null=True, blank=True)
    feedback_note = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["meal_plan", "position"],
                name="uniq_meal_plan_position",
            ),
        ]
        ordering = ["position"]

    def __str__(self):
        return f"plan_item:{self.meal_plan_id}:{self.position}"


class ShoppingList(models.Model):
    meal_plan = models.OneToOneField(
        MealPlan,
        on_delete=models.CASCADE,
        related_name="shopping_list",
    )
    items = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"shopping:{self.meal_plan_id}"

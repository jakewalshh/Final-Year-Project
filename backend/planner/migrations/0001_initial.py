# Generated manually for planner app

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("recipes", "0003_remove_recipe_serves"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MealPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("source_prompt", models.TextField(blank=True, default="")),
                ("parsed_query", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="meal_plans", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="UserPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("excluded_ingredients", models.JSONField(blank=True, default=list)),
                ("preferred_tags", models.JSONField(blank=True, default=list)),
                ("excluded_tags", models.JSONField(blank=True, default=list)),
                ("max_minutes_default", models.PositiveIntegerField(blank=True, null=True)),
                ("nutrition_defaults", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="preferences", to=settings.AUTH_USER_MODEL),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ShoppingList",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("items", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "meal_plan",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="shopping_list", to="planner.mealplan"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="MealPlanItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField()),
                (
                    "meal_plan",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="planner.mealplan"),
                ),
                (
                    "recipe",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="plan_items", to="recipes.recipe"),
                ),
            ],
            options={"ordering": ["position"]},
        ),
        migrations.AddConstraint(
            model_name="mealplanitem",
            constraint=models.UniqueConstraint(fields=("meal_plan", "position"), name="uniq_meal_plan_position"),
        ),
    ]

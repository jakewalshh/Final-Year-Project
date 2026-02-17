from django.test import TestCase
from django.urls import reverse

from .models import Ingredient, Recipe, RecipeIngredient, RecipeStep, RecipeTag, Tag


class RecipeApiTests(TestCase):
    def setUp(self):
        self.recipe = Recipe.objects.create(
            name="Chicken Pasta",
            ingredients="chicken, pasta, garlic",
            instructions="Cook pasta\nCook chicken",
            minutes=30,
            description="Simple dinner",
            external_id=12345,
        )
        ingredient_chicken = Ingredient.objects.create(name="chicken")
        ingredient_pasta = Ingredient.objects.create(name="pasta")
        tag_quick = Tag.objects.create(name="30-minutes-or-less")

        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=ingredient_chicken,
            position=1,
        )
        RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=ingredient_pasta,
            position=2,
        )
        RecipeStep.objects.create(
            recipe=self.recipe,
            step_number=1,
            instruction="Boil pasta",
        )
        RecipeStep.objects.create(
            recipe=self.recipe,
            step_number=2,
            instruction="Cook chicken in a pan",
        )
        RecipeTag.objects.create(recipe=self.recipe, tag=tag_quick)

    def test_search_recipes_by_ingredient(self):
        response = self.client.get(reverse("search-recipes"), {"ingredient": "chicken"})
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["recipes"][0]["name"], "Chicken Pasta")
        self.assertEqual(data["recipes"][0]["ingredients"], ["chicken", "pasta"])

    def test_recipe_detail_returns_steps(self):
        response = self.client.get(reverse("recipe-detail", args=[self.recipe.id]))
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["recipe"]["name"], "Chicken Pasta")
        self.assertEqual(
            data["recipe"]["instructions"],
            ["Boil pasta", "Cook chicken in a pan"],
        )

    def test_plan_meals_fallback_query(self):
        response = self.client.post(
            reverse("plan-meals"),
            data='{"user_prompt": "chicken"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertFalse(data["no_results"])
        self.assertGreaterEqual(len(data["recipes"]), 1)

    def test_plan_meals_local_parser_avoids_allergies_token(self):
        response = self.client.post(
            reverse("plan-meals"),
            data=(
                '{"user_prompt": '
                '"Create 3 meals to feed two people. I want chicken as the meat, there are no allergies"}'
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["query"]["num_meals"], 3)
        self.assertEqual(data["query"]["serves"], 2)
        self.assertEqual(data["query"]["ingredient_keyword"], "chicken")

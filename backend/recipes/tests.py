from django.test import TestCase
from django.urls import reverse

from .models import Ingredient, Recipe, RecipeIngredient, RecipeStep, RecipeTag, Tag


class RecipeApiTests(TestCase):
    def setUp(self):
        self.chicken_recipe = Recipe.objects.create(
            name="Chicken Pasta",
            ingredients="chicken, pasta, garlic",
            instructions="Cook pasta\nCook chicken",
            minutes=30,
            description="Simple dinner",
            external_id=12345,
            calories=420.0,
            protein_pdv=24.0,
            carbohydrates_pdv=12.0,
        )
        self.veg_recipe = Recipe.objects.create(
            name="Quick Veg Stir Fry",
            ingredients="tofu, broccoli, soy sauce",
            instructions="Chop veg\nStir fry all",
            minutes=20,
            description="Quick vegetarian meal",
            external_id=99999,
            calories=280.0,
            protein_pdv=14.0,
            carbohydrates_pdv=9.0,
        )

        ingredient_chicken = Ingredient.objects.create(name="chicken")
        ingredient_pasta = Ingredient.objects.create(name="pasta")
        ingredient_tofu = Ingredient.objects.create(name="tofu")
        ingredient_broccoli = Ingredient.objects.create(name="broccoli")
        tag_quick = Tag.objects.create(name="30-minutes-or-less")
        tag_vegetarian = Tag.objects.create(name="vegetarian")

        RecipeIngredient.objects.create(
            recipe=self.chicken_recipe,
            ingredient=ingredient_chicken,
            position=1,
        )
        RecipeIngredient.objects.create(
            recipe=self.chicken_recipe,
            ingredient=ingredient_pasta,
            position=2,
        )
        RecipeIngredient.objects.create(
            recipe=self.veg_recipe,
            ingredient=ingredient_tofu,
            position=1,
        )
        RecipeIngredient.objects.create(
            recipe=self.veg_recipe,
            ingredient=ingredient_broccoli,
            position=2,
        )
        RecipeStep.objects.create(
            recipe=self.chicken_recipe,
            step_number=1,
            instruction="Boil pasta",
        )
        RecipeStep.objects.create(
            recipe=self.chicken_recipe,
            step_number=2,
            instruction="Cook chicken in a pan",
        )
        RecipeStep.objects.create(
            recipe=self.veg_recipe,
            step_number=1,
            instruction="Chop vegetables",
        )
        RecipeTag.objects.create(recipe=self.chicken_recipe, tag=tag_quick)
        RecipeTag.objects.create(recipe=self.veg_recipe, tag=tag_quick)
        RecipeTag.objects.create(recipe=self.veg_recipe, tag=tag_vegetarian)

    def test_search_recipes_by_ingredient(self):
        response = self.client.get(reverse("search-recipes"), {"ingredient": "chicken"})
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["recipes"][0]["name"], "Chicken Pasta")
        self.assertEqual(data["recipes"][0]["ingredients"], ["chicken", "pasta"])

    def test_recipe_detail_returns_steps(self):
        response = self.client.get(reverse("recipe-detail", args=[self.chicken_recipe.id]))
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
        self.assertEqual(data["query"]["ingredient_keyword"], "chicken")

    def test_plan_meals_returns_new_query_variables(self):
        response = self.client.post(
            reverse("plan-meals"),
            data='{"user_prompt": "Create 2 vegetarian meals under 30 minutes with tofu"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        query = data["query"]
        self.assertEqual(query["num_meals"], 2)
        self.assertIn("tofu", query["ingredient_keywords"])
        self.assertIn("vegetarian", query["include_tags"])
        self.assertEqual(query["max_minutes"], 30)
        self.assertIn(query["parser_source"], ["rules", "openai"])

    def test_plan_meals_exclusion_filters(self):
        response = self.client.post(
            reverse("plan-meals"),
            data='{"user_prompt": "Give me 2 quick meals without chicken"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        recipe_names = [recipe["name"] for recipe in data["recipes"]]
        self.assertNotIn("Chicken Pasta", recipe_names)

    def test_plan_meals_typo_vegetarian_without_ingredient(self):
        response = self.client.post(
            reverse("plan-meals"),
            data='{"user_prompt": "Create 6 vegeterian meals"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertFalse(data["no_results"])
        self.assertIn("vegetarian", data["query"]["include_tags"])
        recipe_names = [recipe["name"] for recipe in data["recipes"]]
        self.assertIn("Quick Veg Stir Fry", recipe_names)

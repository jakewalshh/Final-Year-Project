from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from recipes.models import Ingredient, Recipe, RecipeIngredient, RecipeTag, Tag

from .models import MealPlan, ShoppingList, UserPreference

User = get_user_model()


class PlannerApiTests(APITestCase):
    def setUp(self):
        self.recipe = Recipe.objects.create(
            name="Quick Veg Stir Fry",
            ingredients="tofu, broccoli, soy sauce",
            instructions="Chop\nStir fry",
            minutes=20,
            description="Quick vegetarian meal",
            external_id=20001,
            calories=280,
        )
        ingredient_tofu = Ingredient.objects.create(name="tofu")
        RecipeIngredient.objects.create(recipe=self.recipe, ingredient=ingredient_tofu, position=1)
        vegetarian = Tag.objects.create(name="vegetarian")
        RecipeTag.objects.create(recipe=self.recipe, tag=vegetarian)

    def _register_and_login(self):
        register_resp = self.client.post(
            reverse("auth-register"),
            {
                "email": "test@example.com",
                "password": "StrongPass123!",
                "confirm_password": "StrongPass123!",
            },
            format="json",
        )
        self.assertEqual(register_resp.status_code, 201)

        login_resp = self.client.post(
            reverse("auth-login"),
            {"email": "test@example.com", "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(login_resp.status_code, 200)
        token = login_resp.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_register_login_and_me(self):
        self._register_and_login()
        me_resp = self.client.get(reverse("auth-me"))
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.data["email"], "test@example.com")

    def test_preferences_crud(self):
        self._register_and_login()

        get_resp = self.client.get(reverse("preferences"))
        self.assertEqual(get_resp.status_code, 200)

        put_resp = self.client.put(
            reverse("preferences"),
            {
                "excluded_ingredients": ["fish"],
                "preferred_tags": ["vegetarian"],
                "excluded_tags": [],
                "max_minutes_default": 30,
                "nutrition_defaults": {"max_calories": 500},
            },
            format="json",
        )
        self.assertEqual(put_resp.status_code, 200)
        pref = UserPreference.objects.get(user__email="test@example.com")
        self.assertIn("fish", pref.excluded_ingredients)

    def test_generate_plan_and_shopping_list(self):
        self._register_and_login()

        gen_resp = self.client.post(
            reverse("meal-plan-generate"),
            {"prompt": "Create 2 vegetarian meals with tofu"},
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 200)
        self.assertFalse(gen_resp.data["no_results"])

        plan_id = gen_resp.data["meal_plan"]["id"]
        self.assertTrue(MealPlan.objects.filter(id=plan_id).exists())

        list_resp = self.client.post(reverse("shopping-list", args=[plan_id]), {}, format="json")
        self.assertEqual(list_resp.status_code, 200)
        self.assertTrue(ShoppingList.objects.filter(meal_plan_id=plan_id).exists())

    def test_unauthorized_blocked(self):
        resp = self.client.get(reverse("meal-plan-list"))
        self.assertEqual(resp.status_code, 401)

import os
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from recipes.models import Ingredient, Recipe, RecipeIngredient, RecipeTag, Tag

from .models import MealPlan, MealPlanItem, ShoppingList, UserPreference
from .views import _build_shopping_items_openai

User = get_user_model()


class PlannerApiTests(APITestCase):
    def setUp(self):
        self._old_use_openai_shopping = os.environ.get("USE_OPENAI_SHOPPING_CONDENSER")
        os.environ["USE_OPENAI_SHOPPING_CONDENSER"] = "0"

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

    def tearDown(self):
        if self._old_use_openai_shopping is None:
            os.environ.pop("USE_OPENAI_SHOPPING_CONDENSER", None)
        else:
            os.environ["USE_OPENAI_SHOPPING_CONDENSER"] = self._old_use_openai_shopping

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
            {"prompt": "Create 2 vegetarian meals with tofu", "include_tags": ["vegetarian"]},
            format="json",
        )
        self.assertEqual(gen_resp.status_code, 200)
        self.assertFalse(gen_resp.data["no_results"])

        plan_id = gen_resp.data["meal_plan"]["id"]
        self.assertTrue(MealPlan.objects.filter(id=plan_id).exists())

        list_resp = self.client.post(reverse("shopping-list", args=[plan_id]), {}, format="json")
        self.assertEqual(list_resp.status_code, 200)
        self.assertTrue(ShoppingList.objects.filter(meal_plan_id=plan_id).exists())

    def test_tag_list_endpoint(self):
        self._register_and_login()
        resp = self.client.get(reverse("tag-list"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("tags", resp.data)
        self.assertIn("vegetarian", resp.data["tags"])

    def test_shopping_list_condenses_ingredient_variants(self):
        self._register_and_login()
        user = User.objects.get(email="test@example.com")

        r1 = Recipe.objects.create(
            name="Chicken Bowl 1",
            ingredients="chicken breast, garlic",
            instructions="Cook",
            minutes=20,
            description="x",
            external_id=31001,
        )
        r2 = Recipe.objects.create(
            name="Chicken Bowl 2",
            ingredients="chichken thighs, onion",
            instructions="Cook",
            minutes=25,
            description="y",
            external_id=31002,
        )

        plan = MealPlan.objects.create(
            user=user,
            title="Condense Test",
            source_prompt="test",
            parsed_query={"num_meals": 2},
        )
        MealPlanItem.objects.create(meal_plan=plan, position=1, recipe=r1)
        MealPlanItem.objects.create(meal_plan=plan, position=2, recipe=r2)

        resp = self.client.post(reverse("shopping-list", args=[plan.id]), {}, format="json")
        self.assertEqual(resp.status_code, 200)

        items = {item["ingredient"]: item for item in resp.data["items"]}
        self.assertIn("chicken", items)
        self.assertEqual(items["chicken"]["count"], 2)
        self.assertIn("chicken breast", items["chicken"]["variants"])
        self.assertIn("chichken thighs", items["chicken"]["variants"])

    def test_unauthorized_blocked(self):
        resp = self.client.get(reverse("meal-plan-list"))
        self.assertEqual(resp.status_code, 401)

    def test_openai_condenser_keeps_salt_and_pepper_split(self):
        class _FakeMessage:
            content = (
                '{"normalized_items": ['
                '{"source": "salt and pepper", "canonical": ["salt", "pepper"]},'
                '{"source": "salt", "canonical": ["salt"]},'
                '{"source": "chicken breast", "canonical": ["chicken"]},'
                '{"source": "chichken thighs", "canonical": ["chicken"]}'
                "]}"
            )

        class _FakeChoice:
            message = _FakeMessage()

        class _FakeCompletion:
            choices = [_FakeChoice()]

        class _FakeCompletions:
            @staticmethod
            def create(**kwargs):
                return _FakeCompletion()

        class _FakeChat:
            completions = _FakeCompletions()

        class _FakeOpenAI:
            chat = _FakeChat()

        items = _build_shopping_items_openai(
            ["salt and pepper", "salt", "chicken breast", "chichken thighs"],
            _FakeOpenAI(),
            "gpt-4o-mini",
        )
        self.assertIsNotNone(items)
        item_map = {item["ingredient"]: item for item in items}
        self.assertEqual(item_map["salt"]["count"], 2)
        self.assertEqual(item_map["pepper"]["count"], 1)
        self.assertEqual(item_map["chicken"]["count"], 2)

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import MealPlan, MealPlanItem, ShoppingList, UserPreference

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs["email"].lower().strip()
        attrs["email"] = email

        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})

        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError({"email": "An account with this email already exists."})

        validate_password(attrs["password"])
        return attrs


class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email")


class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = (
            "excluded_ingredients",
            "preferred_tags",
            "excluded_tags",
            "max_minutes_default",
            "nutrition_defaults",
            "updated_at",
        )
        read_only_fields = ("updated_at",)


class MealPlanItemSerializer(serializers.ModelSerializer):
    recipe_id = serializers.IntegerField(source="recipe.id", read_only=True)
    recipe_name = serializers.CharField(source="recipe.name", read_only=True)

    class Meta:
        model = MealPlanItem
        fields = ("position", "recipe_id", "recipe_name")


class MealPlanSerializer(serializers.ModelSerializer):
    items = MealPlanItemSerializer(many=True, read_only=True)

    class Meta:
        model = MealPlan
        fields = (
            "id",
            "title",
            "source_prompt",
            "parsed_query",
            "created_at",
            "updated_at",
            "items",
        )


class MealPlanListSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = MealPlan
        fields = ("id", "title", "created_at", "updated_at", "item_count")


class SwapMealSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True)


class ShoppingListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShoppingList
        fields = ("meal_plan", "items", "created_at")
        read_only_fields = ("created_at",)

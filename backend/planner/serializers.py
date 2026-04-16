from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import MealPlan, MealPlanItem, ShoppingList, UserPreference

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    # Validates registration input and password rules.
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
    # Returns basic authenticated user identity and role flags.
    class Meta:
        model = User
        fields = ("id", "email", "is_staff", "is_superuser")


class UserPreferenceSerializer(serializers.ModelSerializer):
    # Serializes user preference defaults for planner personalization.
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
    # Serializes one item slot within a meal plan.
    recipe_id = serializers.IntegerField(source="recipe.id", read_only=True)
    recipe_name = serializers.CharField(source="recipe.name", read_only=True)

    class Meta:
        model = MealPlanItem
        fields = ("position", "recipe_id", "recipe_name", "rating", "rated_at", "feedback_note")


class MealPlanSerializer(serializers.ModelSerializer):
    # Serializes full meal plan details and completion metrics.
    items = MealPlanItemSerializer(many=True, read_only=True)
    rated_count = serializers.SerializerMethodField()
    total_count = serializers.SerializerMethodField()

    class Meta:
        model = MealPlan
        fields = (
            "id",
            "title",
            "source_prompt",
            "parsed_query",
            "is_completed",
            "completed_at",
            "rated_count",
            "total_count",
            "created_at",
            "updated_at",
            "items",
        )

    def get_rated_count(self, obj):
        return obj.items.filter(rating__isnull=False).count()

    def get_total_count(self, obj):
        return obj.items.count()


class MealPlanListSerializer(serializers.ModelSerializer):
    # Serializes compact meal plan list cards.
    item_count = serializers.IntegerField(source="items.count", read_only=True)
    rated_count = serializers.SerializerMethodField()
    total_count = serializers.SerializerMethodField()

    class Meta:
        model = MealPlan
        fields = ("id", "title", "created_at", "updated_at", "item_count", "is_completed", "completed_at", "rated_count", "total_count")

    def get_rated_count(self, obj):
        return obj.items.filter(rating__isnull=False).count()

    def get_total_count(self, obj):
        return obj.items.count()


class SwapMealSerializer(serializers.Serializer):
    # Validates swap request payload.
    position = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True)


class RateMealSerializer(serializers.Serializer):
    # Validates per-item rating payload.
    position = serializers.IntegerField(min_value=1)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    feedback_note = serializers.CharField(required=False, allow_blank=True)


class ShoppingListSerializer(serializers.ModelSerializer):
    # Serializes stored shopping list payloads.
    class Meta:
        model = ShoppingList
        fields = ("meal_plan", "items", "created_at")
        read_only_fields = ("created_at",)

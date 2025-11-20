from django.shortcuts import render
from django.http import JsonResponse
from .models import Recipe


def sample_plan(request):
    """
    Temporary endpoint:
    - Returns up to 3 recipes that contain 'chicken' in their ingredients.
    - This is just to test the backend <-> DB <-> frontend flow.
    """

    recipes_qs = Recipe.objects.filter(ingredients__icontains="chicken")[:3]

    recipes_data = []
    for r in recipes_qs:
        recipes_data.append({
            "id": r.id,
            "name": r.name,
            "serves": r.serves,
            "ingredients": r.ingredients,
            "instructions": r.instructions,
        })

    return JsonResponse({"recipes": recipes_data})


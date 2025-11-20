import json
import os

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Recipe

from openai import OpenAI

#Creating OpenAI client
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

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

@csrf_exempt  # dev-only: disable CSRF for this endpoint so React can POST
def plan_meals(request):
    """
    Endpoint:
    - Accepts POST with JSON body: { "user_prompt": "..." }
    - Sends the prompt to OpenAI to extract:
        - num_meals (int)
        - serves (int)
        - ingredient_keyword (string, e.g. "chicken")
    - Uses that info to query Recipe objects.
    - Returns JSON: { "query": {..parsed..}, "recipes": [...] }
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    # 1. Parse JSON body
    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    user_prompt = body.get("user_prompt", "").strip()

    if not user_prompt:
        return JsonResponse({"error": "user_prompt is required"}, status=400)

    # 2. Call OpenAI to parse the prompt into structured JSON
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",  # cheaper, fast model is fine for parsing
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a meal planning parser. "
                        "Your job is to extract structured info from the user's request. "
                        "ALWAYS respond with a single JSON object only, no extra text."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Extract the following fields from this request:\n"
                        "- num_meals: how many distinct meals the user asked for (integer)\n"
                        "- serves: how many people each meal should feed (integer)\n"
                        "- ingredient_keyword: a single keyword for the main protein or key ingredient "
                        "(e.g. 'chicken', 'beef', 'tofu'). "
                        "If none is specified, guess something reasonable.\n\n"
                        f"User request: {user_prompt}"
                    ),
                },
            ],
        )

        raw_content = completion.choices[0].message.content
        parsed = json.loads(raw_content)

    except Exception as e:
        # In dev, it's useful to see exactly what went wrong
        print("OpenAI error:", repr(e))
        return JsonResponse(
            {"error": "Failed to parse request with OpenAI"},
            status=500,
        )

    # 3. Extract fields with sane defaults
    num_meals = int(parsed.get("num_meals", 3) or 3)
    serves = int(parsed.get("serves", 2) or 2)
    ingredient_keyword = (parsed.get("ingredient_keyword") or "").strip().lower()

    if not ingredient_keyword:
        ingredient_keyword = "chicken"  # fallback

    # 4. Query recipes based on ingredient keyword (and optionally serves)
    recipes_qs = Recipe.objects.filter(
        ingredients__icontains=ingredient_keyword,
        serves=serves,
    )[:num_meals]

    recipes_data = [
        {
            "id": r.id,
            "name": r.name,
            "serves": r.serves,
            "ingredients": r.ingredients,
            "instructions": r.instructions,
        }
        for r in recipes_qs
    ]

    # 5. Return both the parsed query info and the recipes
    return JsonResponse(
        {
            "query": {
                "num_meals": num_meals,
                "serves": serves,
                "ingredient_keyword": ingredient_keyword,
            },
            "recipes": recipes_data,
        }
    )

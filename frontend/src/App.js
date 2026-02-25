import React, { useState } from "react";
import "./App.css";

const PLAN_MEALS_URL = "http://localhost:8000/api/plan-meals/";
const SEARCH_RECIPES_URL = "http://localhost:8000/api/recipes/search/";

function App() {
  const [mode, setMode] = useState("plan");
  const [userPrompt, setUserPrompt] = useState(
    "Create 3 meals to feed two people. I want chicken as the meat, there are no alergies"
  );
  const [searchFilters, setSearchFilters] = useState({
    q: "",
    ingredient: "chicken",
    tag: "",
    max_minutes: "",
    limit: "10",
    offset: "0",
  });
  const [recipes, setRecipes] = useState([]);
  const [parsedQuery, setParsedQuery] = useState(null);
  const [searchMeta, setSearchMeta] = useState(null);
  const [noResults, setNoResults] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showNutrition, setShowNutrition] = useState(false);

  const formatNutritionValue = (value) => {
    if (value === null || value === undefined) return "N/A";
    if (typeof value === "number") return Number.isInteger(value) ? value : value.toFixed(1);
    return value;
  };

  const setFilter = (key, value) => {
    setSearchFilters((prev) => ({ ...prev, [key]: value }));
  };

  const handlePlanSubmit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setRecipes([]);
    setSearchMeta(null);
    setParsedQuery(null);
    setNoResults(false);

    try {
      const response = await fetch(PLAN_MEALS_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_prompt: userPrompt,
        }),
      });

      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
      }

      const data = await response.json();

      // Expecting { query: {...}, recipes: [...] }
      setRecipes(data.recipes || []);
      setParsedQuery(data.query || null);
      setNoResults(Boolean(data.no_results));
    } catch (err) {
      console.error(err);
      setError("Something went wrong generating the meal plan. Check the backend logs.");
    } finally {
      setLoading(false);
    }
  };

  const handleSearchSubmit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setRecipes([]);
    setParsedQuery(null);
    setSearchMeta(null);
    setNoResults(false);

    try {
      const params = new URLSearchParams();
      Object.entries(searchFilters).forEach(([key, value]) => {
        const trimmedValue = String(value).trim();
        if (trimmedValue !== "") params.set(key, trimmedValue);
      });

      const response = await fetch(`${SEARCH_RECIPES_URL}?${params.toString()}`);
      if (!response.ok) {
        throw new Error(`Search failed with status ${response.status}`);
      }

      const data = await response.json();
      const returnedRecipes = data.recipes || [];
      setRecipes(returnedRecipes);
      setNoResults(returnedRecipes.length === 0);
      setSearchMeta({
        total: data.total,
        count: data.count,
        limit: data.limit,
        offset: data.offset,
        activeFilters: Object.fromEntries(
          Object.entries(searchFilters).filter(([, value]) => String(value).trim() !== "")
        ),
      });
    } catch (err) {
      console.error(err);
      setError("Something went wrong running recipe search.");
    } finally {
      setLoading(false);
    }
  };

  const switchMode = (nextMode) => {
    setMode(nextMode);
    setError("");
    setRecipes([]);
    setNoResults(false);
    setParsedQuery(null);
    setSearchMeta(null);
  };

  return (
    <div className="page">
      <div className="card">
        <h1 className="title">Panion Prototype</h1>
        <p className="subtitle">Query your recipe database with prompt mode or filter mode.</p>

        <div className="mode-switch">
          <button
            type="button"
            className={`button secondary ${mode === "plan" ? "active-mode" : ""}`}
            onClick={() => switchMode("plan")}
          >
            Plan Meals
          </button>
          <button
            type="button"
            className={`button secondary ${mode === "search" ? "active-mode" : ""}`}
            onClick={() => switchMode("search")}
          >
            Search Recipes
          </button>
        </div>

        {mode === "plan" && (
          <form onSubmit={handlePlanSubmit} className="form">
            <label className="label">
              Meal plan request:
              <textarea
                className="textarea"
                value={userPrompt}
                onChange={(e) => setUserPrompt(e.target.value)}
              />
            </label>

            <button type="submit" className="button" disabled={loading}>
              {loading ? "Generating..." : "Generate Meal Plan"}
            </button>
          </form>
        )}

        {mode === "search" && (
          <form onSubmit={handleSearchSubmit} className="form">
            <div className="filter-grid">
              <label className="label">
                Text query (`q`)
                <input
                  className="input"
                  value={searchFilters.q}
                  onChange={(e) => setFilter("q", e.target.value)}
                />
              </label>

              <label className="label">
                Ingredient
                <input
                  className="input"
                  value={searchFilters.ingredient}
                  onChange={(e) => setFilter("ingredient", e.target.value)}
                />
              </label>

              <label className="label">
                Tag
                <input
                  className="input"
                  value={searchFilters.tag}
                  onChange={(e) => setFilter("tag", e.target.value)}
                />
              </label>

              <label className="label">
                Max minutes
                <input
                  className="input"
                  type="number"
                  min="0"
                  value={searchFilters.max_minutes}
                  onChange={(e) => setFilter("max_minutes", e.target.value)}
                />
              </label>

              <label className="label">
                Limit
                <input
                  className="input"
                  type="number"
                  min="1"
                  max="100"
                  value={searchFilters.limit}
                  onChange={(e) => setFilter("limit", e.target.value)}
                />
              </label>

              <label className="label">
                Offset
                <input
                  className="input"
                  type="number"
                  min="0"
                  value={searchFilters.offset}
                  onChange={(e) => setFilter("offset", e.target.value)}
                />
              </label>
            </div>

            <button type="submit" className="button" disabled={loading}>
              {loading ? "Searching..." : "Search Recipes"}
            </button>
          </form>
        )}

        <button
          type="button"
          className="button secondary"
          onClick={() => setShowNutrition((prev) => !prev)}
        >
          {showNutrition ? "Hide Nutrition" : "Show Nutrition"}
        </button>

        {error && <p className="error">{error}</p>}

        {mode === "plan" && parsedQuery && (
          <div className="query-summary">
            <h2 className="results-title">Parsed Request</h2>
            <p className="query-text">
              <strong>Meals:</strong> {parsedQuery.num_meals} &nbsp;|&nbsp;
              <strong>Main ingredient:</strong> {parsedQuery.ingredient_keyword}
            </p>
          </div>
        )}

        {mode === "search" && searchMeta && (
          <div className="query-summary">
            <h2 className="results-title">Search Query Used</h2>
            <p className="query-text">
              <strong>Total matches:</strong> {searchMeta.total} &nbsp;|&nbsp;
              <strong>Returned:</strong> {searchMeta.count} &nbsp;|&nbsp;
              <strong>Limit:</strong> {searchMeta.limit} &nbsp;|&nbsp;
              <strong>Offset:</strong> {searchMeta.offset}
            </p>
            <p className="query-text">
              <strong>Active filters:</strong>{" "}
              {Object.keys(searchMeta.activeFilters).length > 0
                ? Object.entries(searchMeta.activeFilters)
                    .map(([key, value]) => `${key}=${value}`)
                    .join(", ")
                : "none"}
            </p>
          </div>
        )}

        <div className="results">
          <h2 className="results-title">Recipes</h2>

          {recipes.length === 0 && !loading && !noResults && (
            <p className="no-results">No recipes yet. Try generating a plan.</p>
          )}

          {noResults && !loading && (
            <p className="no-results">
              No recipes found for this request. Try changing the main ingredient.
            </p>
          )}


          {recipes.map((recipe) => (
            <div key={recipe.id} className="recipe-card">
              <h3 className="recipe-title">{recipe.name}</h3>
              <p>
                <strong>Ingredients:</strong>{" "}
                {Array.isArray(recipe.ingredients)
                  ? recipe.ingredients.join(", ")
                  : recipe.ingredients}
              </p>
              <div>
                <strong>Instructions:</strong>
                {Array.isArray(recipe.instructions) && recipe.instructions.length > 0 ? (
                  <ol>
                    {recipe.instructions.map((step, index) => (
                      <li key={`${recipe.id}-step-${index}`}>{step}</li>
                    ))}
                  </ol>
                ) : (
                  <p>{recipe.instructions || "Not included in search results. Open recipe detail endpoint for full steps."}</p>
                )}
              </div>

              {showNutrition && recipe.nutrition && (
                <div className="nutrition-panel">
                  <strong>Nutrition (per recipe):</strong>
                  <ul>
                    <li>Calories: {formatNutritionValue(recipe.nutrition.calories)}</li>
                    <li>Total Fat (%DV): {formatNutritionValue(recipe.nutrition.total_fat_pdv)}</li>
                    <li>Sugar (%DV): {formatNutritionValue(recipe.nutrition.sugar_pdv)}</li>
                    <li>Sodium (%DV): {formatNutritionValue(recipe.nutrition.sodium_pdv)}</li>
                    <li>Protein (%DV): {formatNutritionValue(recipe.nutrition.protein_pdv)}</li>
                    <li>Saturated Fat (%DV): {formatNutritionValue(recipe.nutrition.saturated_fat_pdv)}</li>
                    <li>Carbohydrates (%DV): {formatNutritionValue(recipe.nutrition.carbohydrates_pdv)}</li>
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default App;

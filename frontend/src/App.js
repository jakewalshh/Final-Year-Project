import React, { useState } from "react";
import "./App.css";

const PLAN_MEALS_URL = "http://localhost:8000/api/plan-meals/";
const SEARCH_RECIPES_URL = "http://localhost:8000/api/recipes/search/";
const QUICK_PROMPTS = [
  "Create 4 vegetarian meals under 30 minutes",
  "Make me 3 high protein chicken meals",
  "Make me 4 vegetarian meals, exclude seed",
  "Make me 4 vegetarian meals, i am extremely allergic to fish",
];

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
  const [showDevInspector, setShowDevInspector] = useState(true);

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

  const renderQueryList = (title, values) => (
    <div className="summary-row">
      <span className="summary-key">{title}</span>
      <span className="summary-value">
        {Array.isArray(values) ? (values.length > 0 ? values.join(", ") : "none") : values || "none"}
      </span>
    </div>
  );

  const renderRecipeMeta = (recipe) => (
    <div className="recipe-meta">
      <span className="chip">{recipe.minutes ? `${recipe.minutes} min` : "time n/a"}</span>
      <span className="chip">{recipe.n_ingredients ?? "?"} ingredients</span>
      <span className="chip">{recipe.n_steps ?? "?"} steps</span>
      {Array.isArray(recipe.tags) &&
        recipe.tags.slice(0, 4).map((tag) => (
          <span key={`${recipe.id}-${tag}`} className="chip tag-chip">
            {tag}
          </span>
        ))}
    </div>
  );

  return (
    <div className="page">
      <div className="card">
        <div className="hero">
          <h1 className="title">Panion Meal Planner</h1>
          <p className="subtitle">
            Consumer mode with dev visibility. Plan with natural language or query directly with filters.
          </p>
        </div>

        <div className="layout-grid">
          <section className="panel panel-input">
            <h2 className="panel-title">1) Build Your Request</h2>
            <p className="panel-description">
              Use conversational planning or direct search. Switch mode anytime.
            </p>

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
                  Meal plan request
                  <textarea
                    className="textarea"
                    value={userPrompt}
                    onChange={(e) => setUserPrompt(e.target.value)}
                    placeholder="Example: Create 4 vegetarian meals under 30 minutes"
                  />
                </label>

                <div className="quick-prompts">
                  {QUICK_PROMPTS.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      className="quick-prompt"
                      onClick={() => setUserPrompt(prompt)}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>

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
                      placeholder="pasta bake"
                    />
                  </label>

                  <label className="label">
                    Ingredient
                    <input
                      className="input"
                      value={searchFilters.ingredient}
                      onChange={(e) => setFilter("ingredient", e.target.value)}
                      placeholder="chicken"
                    />
                  </label>

                  <label className="label">
                    Tag
                    <input
                      className="input"
                      value={searchFilters.tag}
                      onChange={(e) => setFilter("tag", e.target.value)}
                      placeholder="vegetarian"
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

            <div className="toggle-row">
              <button
                type="button"
                className="button secondary"
                onClick={() => setShowNutrition((prev) => !prev)}
              >
                {showNutrition ? "Hide Nutrition" : "Show Nutrition"}
              </button>
              <button
                type="button"
                className="button secondary"
                onClick={() => setShowDevInspector((prev) => !prev)}
              >
                {showDevInspector ? "Hide Dev Inspector" : "Show Dev Inspector"}
              </button>
            </div>
            {error && <p className="error">{error}</p>}
          </section>

          <section className="panel panel-summary">
            <h2 className="panel-title">2) Query Interpretation</h2>
            {mode === "plan" && parsedQuery && (
              <div className="summary-block">
                {renderQueryList("Meals", parsedQuery.num_meals)}
                {renderQueryList("Main ingredient", parsedQuery.ingredient_keyword || "not specified")}
                {renderQueryList("Include tags", parsedQuery.include_tags)}
                {renderQueryList("Exclude ingredients", parsedQuery.exclude_ingredients)}
                {renderQueryList("Max minutes", parsedQuery.max_minutes)}
                {renderQueryList("Parser", parsedQuery.parser_source || "rules")}
              </div>
            )}

            {mode === "search" && searchMeta && (
              <div className="summary-block">
                {renderQueryList("Total matches", searchMeta.total)}
                {renderQueryList("Returned", searchMeta.count)}
                {renderQueryList("Limit", searchMeta.limit)}
                {renderQueryList("Offset", searchMeta.offset)}
                {renderQueryList(
                  "Active filters",
                  Object.keys(searchMeta.activeFilters).length > 0
                    ? Object.entries(searchMeta.activeFilters)
                        .map(([key, value]) => `${key}=${value}`)
                        .join(", ")
                    : "none"
                )}
              </div>
            )}

            {!parsedQuery && !searchMeta && (
              <p className="panel-description">
                Submit a request to see parsed variables and applied filters.
              </p>
            )}

            {showDevInspector && (
              <details className="dev-details" open>
                <summary>Developer Inspector</summary>
                <pre>
                  {JSON.stringify(
                    mode === "plan"
                      ? parsedQuery || { note: "No parsed query yet" }
                      : searchMeta || { note: "No search metadata yet" },
                    null,
                    2
                  )}
                </pre>
              </details>
            )}
          </section>
        </div>

        <section className="results">
          <h2 className="results-title">3) Recipes</h2>

          {recipes.length === 0 && !loading && !noResults && (
            <p className="no-results">No recipes yet. Try generating a plan.</p>
          )}

          {noResults && !loading && (
            <p className="no-results">
              No recipes found for this request. Try changing the main ingredient.
            </p>
          )}

          <div className="recipe-grid">
            {recipes.map((recipe) => (
              <article key={recipe.id} className="recipe-card">
                <h3 className="recipe-title">{recipe.name}</h3>
                {renderRecipeMeta(recipe)}
                <p className="recipe-copy">
                  <strong>Ingredients:</strong>{" "}
                  {Array.isArray(recipe.ingredients)
                    ? recipe.ingredients.join(", ")
                    : recipe.ingredients}
                </p>
                <div className="recipe-copy">
                  <strong>Instructions:</strong>
                  {Array.isArray(recipe.instructions) && recipe.instructions.length > 0 ? (
                    <ol>
                      {recipe.instructions.map((step, index) => (
                        <li key={`${recipe.id}-step-${index}`}>{step}</li>
                      ))}
                    </ol>
                  ) : (
                    <p>
                      {recipe.instructions ||
                        "Not included in search results. Open recipe detail endpoint for full steps."}
                    </p>
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
                      <li>
                        Saturated Fat (%DV): {formatNutritionValue(recipe.nutrition.saturated_fat_pdv)}
                      </li>
                      <li>
                        Carbohydrates (%DV): {formatNutritionValue(recipe.nutrition.carbohydrates_pdv)}
                      </li>
                    </ul>
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

export default App;

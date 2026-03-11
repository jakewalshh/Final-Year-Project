import React, { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE = process.env.REACT_APP_API_BASE_URL || "http://localhost:8000/api";

const QUICK_PROMPTS = [
  "Create 4 vegetarian meals under 30 minutes",
  "Make me 4 vegetarian meals, i am extremely allergic to fish",
  "Give me 5 high protein chicken meals, no peanuts",
  "Create 3 quick dinners with tofu and max 500 calories",
];

const toCsv = (value) =>
  (value || [])
    .map((x) => String(x || "").trim())
    .filter(Boolean)
    .join(", ");

const fromCsv = (value) =>
  String(value || "")
    .split(",")
    .map((x) => x.trim().toLowerCase())
    .filter(Boolean);

function App() {
  const [authMode, setAuthMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [accessToken, setAccessToken] = useState(localStorage.getItem("panion_access") || "");
  const [refreshToken, setRefreshToken] = useState(localStorage.getItem("panion_refresh") || "");
  const [currentUser, setCurrentUser] = useState(() => {
    const raw = localStorage.getItem("panion_user");
    return raw ? JSON.parse(raw) : null;
  });

  const [appTab, setAppTab] = useState("plan");
  const [prompt, setPrompt] = useState("Create 4 vegetarian meals under 30 minutes");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showNutrition, setShowNutrition] = useState(false);
  const [showDevInspector, setShowDevInspector] = useState(true);

  const [parsedQuery, setParsedQuery] = useState(null);
  const [recipes, setRecipes] = useState([]);
  const [mealPlan, setMealPlan] = useState(null);
  const [savedPlans, setSavedPlans] = useState([]);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const [shoppingList, setShoppingList] = useState(null);

  const [preferences, setPreferences] = useState({
    excluded_ingredients: [],
    preferred_tags: [],
    excluded_tags: [],
    max_minutes_default: "",
    nutrition_defaults: {},
  });
  const [prefFields, setPrefFields] = useState({
    excluded_ingredients: "",
    preferred_tags: "",
    excluded_tags: "",
    max_minutes_default: "",
    max_calories: "",
    min_protein_pdv: "",
    max_carbs_pdv: "",
  });

  const parserWarnings = useMemo(() => {
    if (!parsedQuery) return [];
    return Array.isArray(parsedQuery.parser_warnings) ? parsedQuery.parser_warnings : [];
  }, [parsedQuery]);

  const persistAuth = (payload) => {
    const access = payload?.access || "";
    const refresh = payload?.refresh || "";
    const user = payload?.user || (payload?.email ? { id: payload.user_id, email: payload.email } : null);

    setAccessToken(access);
    setRefreshToken(refresh);
    setCurrentUser(user);

    localStorage.setItem("panion_access", access);
    localStorage.setItem("panion_refresh", refresh);
    if (user) localStorage.setItem("panion_user", JSON.stringify(user));
  };

  const clearAuth = () => {
    setAccessToken("");
    setRefreshToken("");
    setCurrentUser(null);
    localStorage.removeItem("panion_access");
    localStorage.removeItem("panion_refresh");
    localStorage.removeItem("panion_user");

    setSavedPlans([]);
    setSelectedPlan(null);
    setSelectedPlanId("");
    setShoppingList(null);
    setParsedQuery(null);
    setRecipes([]);
    setMealPlan(null);
    setPreferences({
      excluded_ingredients: [],
      preferred_tags: [],
      excluded_tags: [],
      max_minutes_default: "",
      nutrition_defaults: {},
    });
    setPrefFields({
      excluded_ingredients: "",
      preferred_tags: "",
      excluded_tags: "",
      max_minutes_default: "",
      max_calories: "",
      min_protein_pdv: "",
      max_carbs_pdv: "",
    });
  };

  const apiFetch = async (path, options = {}, canRetry = true, tokenOverride = null) => {
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };

    const tokenForRequest = tokenOverride || accessToken;
    if (tokenForRequest && options.auth !== false) {
      headers.Authorization = `Bearer ${tokenForRequest}`;
    }

    const response = await fetch(`${API_BASE}${path}`, {
      method: options.method || "GET",
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });

    if (response.status === 401 && canRetry && refreshToken && options.auth !== false) {
      const refreshResp = await fetch(`${API_BASE}/auth/refresh/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh: refreshToken }),
      });

      if (refreshResp.ok) {
        const refreshData = await refreshResp.json();
        setAccessToken(refreshData.access);
        localStorage.setItem("panion_access", refreshData.access);
        return apiFetch(path, options, false, refreshData.access);
      }

      clearAuth();
      throw new Error("Session expired. Please log in again.");
    }

    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try {
        const errData = await response.json();
        message = errData.detail || errData.error || JSON.stringify(errData);
      } catch (parseError) {
        // keep fallback message
      }
      throw new Error(message);
    }

    if (response.status === 204) return null;
    return response.json();
  };

  const loadProfile = async () => {
    const me = await apiFetch("/auth/me/");
    setCurrentUser(me);
    localStorage.setItem("panion_user", JSON.stringify(me));
  };

  const loadPreferences = async () => {
    const data = await apiFetch("/preferences/");
    setPreferences(data);
    setPrefFields({
      excluded_ingredients: toCsv(data.excluded_ingredients),
      preferred_tags: toCsv(data.preferred_tags),
      excluded_tags: toCsv(data.excluded_tags),
      max_minutes_default: data.max_minutes_default || "",
      max_calories: data.nutrition_defaults?.max_calories ?? "",
      min_protein_pdv: data.nutrition_defaults?.min_protein_pdv ?? "",
      max_carbs_pdv: data.nutrition_defaults?.max_carbs_pdv ?? "",
    });
  };

  const loadSavedPlans = async () => {
    const data = await apiFetch("/meal-plans/");
    setSavedPlans(Array.isArray(data) ? data : []);
  };

  const loadPlanDetail = async (planId) => {
    if (!planId) return;
    const data = await apiFetch(`/meal-plans/${planId}/`);
    setSelectedPlan(data);
    setSelectedPlanId(String(planId));
  };

  const loadShoppingList = async (planId) => {
    if (!planId) return;
    const data = await apiFetch(`/meal-plans/${planId}/shopping-list/`);
    setShoppingList(data);
    setSelectedPlanId(String(planId));
  };

  useEffect(() => {
    if (!accessToken) return;

    const boot = async () => {
      setError("");
      try {
        await Promise.all([loadProfile(), loadPreferences(), loadSavedPlans()]);
      } catch (err) {
        setError(err.message);
      }
    };

    boot();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  const handleAuthSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setNotice("");
    setLoading(true);

    try {
      if (authMode === "register") {
        const data = await apiFetch(
          "/auth/register/",
          {
            method: "POST",
            body: { email, password, confirm_password: confirmPassword },
            auth: false,
          },
          false
        );
        persistAuth(data);
        setNotice("Account created and logged in.");
      } else {
        const data = await apiFetch(
          "/auth/login/",
          {
            method: "POST",
            body: { email, password },
            auth: false,
          },
          false
        );
        persistAuth(data);
        setNotice("Logged in.");
      }
      setPassword("");
      setConfirmPassword("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleGeneratePlan = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setNotice("");
    setParsedQuery(null);
    setRecipes([]);
    setMealPlan(null);

    try {
      const data = await apiFetch("/meal-plans/generate/", {
        method: "POST",
        body: { prompt },
      });

      setParsedQuery(data.query || null);
      setRecipes(data.recipes || []);
      setMealPlan(data.meal_plan || null);
      setNotice(data.no_results ? "No results found for current constraints." : "Meal plan generated and saved.");

      await loadSavedPlans();
      if (data.meal_plan?.id) {
        setSelectedPlanId(String(data.meal_plan.id));
        await loadPlanDetail(data.meal_plan.id);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSavePreferences = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setNotice("");

    try {
      const payload = {
        excluded_ingredients: fromCsv(prefFields.excluded_ingredients),
        preferred_tags: fromCsv(prefFields.preferred_tags),
        excluded_tags: fromCsv(prefFields.excluded_tags),
        max_minutes_default: prefFields.max_minutes_default
          ? Number(prefFields.max_minutes_default)
          : null,
        nutrition_defaults: {
          ...(prefFields.max_calories !== "" ? { max_calories: Number(prefFields.max_calories) } : {}),
          ...(prefFields.min_protein_pdv !== "" ? { min_protein_pdv: Number(prefFields.min_protein_pdv) } : {}),
          ...(prefFields.max_carbs_pdv !== "" ? { max_carbs_pdv: Number(prefFields.max_carbs_pdv) } : {}),
        },
      };

      const data = await apiFetch("/preferences/", { method: "PUT", body: payload });
      setPreferences(data);
      setNotice("Preferences updated.");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDeletePlan = async (planId) => {
    setLoading(true);
    setError("");
    setNotice("");
    try {
      await apiFetch(`/meal-plans/${planId}/`, { method: "DELETE" });
      setNotice("Plan deleted.");
      if (selectedPlanId === String(planId)) {
        setSelectedPlan(null);
        setSelectedPlanId("");
        setShoppingList(null);
      }
      await loadSavedPlans();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateShoppingList = async (planId) => {
    if (!planId) return;
    setLoading(true);
    setError("");
    setNotice("");

    try {
      const data = await apiFetch(`/meal-plans/${planId}/shopping-list/`, { method: "POST", body: {} });
      setShoppingList(data);
      setSelectedPlanId(String(planId));
      setNotice("Shopping list generated.");
      setAppTab("shopping");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSwapMeal = async (position) => {
    if (!selectedPlan?.id) return;
    setLoading(true);
    setError("");
    setNotice("");

    try {
      await apiFetch(`/meal-plans/${selectedPlan.id}/swap/`, {
        method: "POST",
        body: { position },
      });
      await loadPlanDetail(selectedPlan.id);
      setNotice(`Swapped meal at position ${position}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const formatNutrition = (recipe) => {
    if (!recipe?.nutrition) return null;
    const n = recipe.nutrition;
    return (
      <div className="nutrition-panel">
        <strong>Nutrition:</strong>
        <ul>
          <li>Calories: {n.calories ?? "N/A"}</li>
          <li>Protein (%DV): {n.protein_pdv ?? "N/A"}</li>
          <li>Carbs (%DV): {n.carbohydrates_pdv ?? "N/A"}</li>
          <li>Fat (%DV): {n.total_fat_pdv ?? "N/A"}</li>
          <li>Sodium (%DV): {n.sodium_pdv ?? "N/A"}</li>
        </ul>
      </div>
    );
  };

  if (!accessToken) {
    return (
      <div className="page">
        <div className="auth-card">
          <h1>Panion</h1>
          <p>Sign in to save plans, preferences, and shopping lists.</p>

          <div className="auth-toggle">
            <button
              type="button"
              className={`button secondary ${authMode === "login" ? "active-mode" : ""}`}
              onClick={() => setAuthMode("login")}
            >
              Login
            </button>
            <button
              type="button"
              className={`button secondary ${authMode === "register" ? "active-mode" : ""}`}
              onClick={() => setAuthMode("register")}
            >
              Register
            </button>
          </div>

          <form onSubmit={handleAuthSubmit} className="form">
            <label className="label">
              Email
              <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label className="label">
              Password
              <input
                className="input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {authMode === "register" && (
              <label className="label">
                Confirm password
                <input
                  className="input"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                />
              </label>
            )}
            <button type="submit" className="button" disabled={loading}>
              {loading ? "Please wait..." : authMode === "register" ? "Create Account" : "Login"}
            </button>
          </form>

          {error && <p className="error">{error}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="card">
        <header className="topbar">
          <div>
            <h1 className="title">Panion</h1>
            <p className="subtitle">AI-assisted meal planning with saved plans, preferences, and shopping lists.</p>
          </div>
          <div className="user-actions">
            <span className="chip">{currentUser?.email}</span>
            <button type="button" className="button secondary" onClick={clearAuth}>
              Logout
            </button>
          </div>
        </header>

        <nav className="tabs">
          {[
            ["plan", "Plan"],
            ["saved", "Saved Plans"],
            ["preferences", "Preferences"],
            ["shopping", "Shopping List"],
          ].map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`button secondary ${appTab === key ? "active-mode" : ""}`}
              onClick={() => setAppTab(key)}
            >
              {label}
            </button>
          ))}
        </nav>

        {(error || notice) && (
          <div className="status-strip">
            {error && <span className="error">{error}</span>}
            {notice && <span className="ok">{notice}</span>}
          </div>
        )}

        {appTab === "plan" && (
          <div className="layout-grid">
            <section className="panel">
              <h2 className="panel-title">Generate Plan</h2>
              <form className="form" onSubmit={handleGeneratePlan}>
                <label className="label">
                  Prompt
                  <textarea className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
                </label>
                <div className="quick-prompts">
                  {QUICK_PROMPTS.map((x) => (
                    <button key={x} type="button" className="quick-prompt" onClick={() => setPrompt(x)}>
                      {x}
                    </button>
                  ))}
                </div>
                <div className="toggle-row">
                  <button className="button" type="submit" disabled={loading}>
                    {loading ? "Generating..." : "Generate Meal Plan"}
                  </button>
                  {mealPlan?.id && (
                    <button
                      type="button"
                      className="button secondary"
                      onClick={() => handleGenerateShoppingList(mealPlan.id)}
                      disabled={loading}
                    >
                      Build Shopping List
                    </button>
                  )}
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => setShowNutrition((v) => !v)}
                  >
                    {showNutrition ? "Hide Nutrition" : "Show Nutrition"}
                  </button>
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => setShowDevInspector((v) => !v)}
                  >
                    {showDevInspector ? "Hide Parsed" : "Show Parsed"}
                  </button>
                </div>
              </form>
            </section>

            <section className="panel">
              <h2 className="panel-title">Parsed Request</h2>
              {!parsedQuery && <p className="panel-description">Generate a plan to inspect parser output.</p>}
              {parsedQuery && (
                <div className="summary-block">
                  <div className="summary-row"><span className="summary-key">Meals</span><span>{parsedQuery.num_meals}</span></div>
                  <div className="summary-row"><span className="summary-key">Ingredients</span><span>{toCsv(parsedQuery.ingredient_keywords) || "none"}</span></div>
                  <div className="summary-row"><span className="summary-key">Include tags</span><span>{toCsv(parsedQuery.include_tags) || "none"}</span></div>
                  <div className="summary-row"><span className="summary-key">Exclude tags</span><span>{toCsv(parsedQuery.exclude_tags) || "none"}</span></div>
                  <div className="summary-row"><span className="summary-key">Exclude ingredients</span><span>{toCsv(parsedQuery.exclude_ingredients) || "none"}</span></div>
                  <div className="summary-row"><span className="summary-key">Max minutes</span><span>{parsedQuery.max_minutes ?? "none"}</span></div>
                  <div className="summary-row"><span className="summary-key">Max calories</span><span>{parsedQuery.max_calories ?? "none"}</span></div>
                  <div className="summary-row"><span className="summary-key">Min protein %DV</span><span>{parsedQuery.min_protein_pdv ?? "none"}</span></div>
                  <div className="summary-row"><span className="summary-key">Max carbs %DV</span><span>{parsedQuery.max_carbs_pdv ?? "none"}</span></div>
                  <div className="summary-row"><span className="summary-key">Parser</span><span>{parsedQuery.parser_source || "rules"}</span></div>
                </div>
              )}

              {parserWarnings.length > 0 && (
                <div className="warning-panel">
                  <strong>Parser warnings</strong>
                  <ul>
                    {parserWarnings.map((w, i) => (
                      <li key={`${w}-${i}`}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}

              {showDevInspector && (
                <details className="dev-details" open>
                  <summary>Developer inspector</summary>
                  <pre>{JSON.stringify(parsedQuery || { note: "No parsed request yet" }, null, 2)}</pre>
                </details>
              )}
            </section>

            <section className="panel panel-wide">
              <h2 className="panel-title">Recipes</h2>
              {!recipes.length && <p className="panel-description">No recipes yet.</p>}
              <div className="recipe-grid">
                {recipes.map((recipe) => (
                  <article key={recipe.id} className="recipe-card">
                    <h3 className="recipe-title">{recipe.name}</h3>
                    <div className="recipe-meta">
                      <span className="chip">{recipe.minutes || "?"} min</span>
                      <span className="chip">{recipe.n_ingredients ?? "?"} ingredients</span>
                      <span className="chip">{recipe.n_steps ?? "?"} steps</span>
                    </div>
                    <p className="recipe-copy"><strong>Ingredients:</strong> {Array.isArray(recipe.ingredients) ? recipe.ingredients.join(", ") : recipe.ingredients}</p>
                    <div className="recipe-copy">
                      <strong>Instructions:</strong>
                      {Array.isArray(recipe.instructions) && recipe.instructions.length > 0 ? (
                        <ol>
                          {recipe.instructions.map((step, idx) => (
                            <li key={`${recipe.id}-${idx}`}>{step}</li>
                          ))}
                        </ol>
                      ) : (
                        <p>No steps in list view.</p>
                      )}
                    </div>
                    {showNutrition && formatNutrition(recipe)}
                  </article>
                ))}
              </div>
            </section>
          </div>
        )}

        {appTab === "saved" && (
          <div className="layout-grid two-col">
            <section className="panel">
              <h2 className="panel-title">Saved Plans</h2>
              <button type="button" className="button secondary" onClick={loadSavedPlans} disabled={loading}>
                Refresh
              </button>
              <div className="list-block">
                {savedPlans.length === 0 && <p className="panel-description">No saved plans yet.</p>}
                {savedPlans.map((plan) => (
                  <div key={plan.id} className={`list-item ${selectedPlanId === String(plan.id) ? "selected" : ""}`}>
                    <div>
                      <strong>{plan.title}</strong>
                      <div className="panel-description">{new Date(plan.created_at).toLocaleString()}</div>
                    </div>
                    <div className="row-actions">
                      <button type="button" className="button secondary" onClick={() => loadPlanDetail(plan.id)}>
                        Open
                      </button>
                      <button type="button" className="button secondary" onClick={() => handleGenerateShoppingList(plan.id)}>
                        Shop
                      </button>
                      <button type="button" className="button secondary" onClick={() => handleDeletePlan(plan.id)}>
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel">
              <h2 className="panel-title">Plan Detail</h2>
              {!selectedPlan && <p className="panel-description">Select a plan to see details.</p>}
              {selectedPlan && (
                <>
                  <p><strong>{selectedPlan.title}</strong></p>
                  <p className="panel-description">Prompt: {selectedPlan.source_prompt}</p>
                  <div className="list-block">
                    {(selectedPlan.items || []).map((item) => (
                      <div key={item.position} className="list-item compact">
                        <div>
                          <strong>#{item.position}</strong> {item.recipe_name}
                        </div>
                        <button
                          type="button"
                          className="button secondary"
                          onClick={() => handleSwapMeal(item.position)}
                        >
                          Swap
                        </button>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </section>
          </div>
        )}

        {appTab === "preferences" && (
          <section className="panel">
            <h2 className="panel-title">Preferences</h2>
            <form className="form" onSubmit={handleSavePreferences}>
              <div className="filter-grid">
                <label className="label">
                  Excluded ingredients (comma-separated)
                  <input
                    className="input"
                    value={prefFields.excluded_ingredients}
                    onChange={(e) => setPrefFields((p) => ({ ...p, excluded_ingredients: e.target.value }))}
                  />
                </label>
                <label className="label">
                  Preferred tags
                  <input
                    className="input"
                    value={prefFields.preferred_tags}
                    onChange={(e) => setPrefFields((p) => ({ ...p, preferred_tags: e.target.value }))}
                  />
                </label>
                <label className="label">
                  Excluded tags
                  <input
                    className="input"
                    value={prefFields.excluded_tags}
                    onChange={(e) => setPrefFields((p) => ({ ...p, excluded_tags: e.target.value }))}
                  />
                </label>
                <label className="label">
                  Default max minutes
                  <input
                    className="input"
                    type="number"
                    min="1"
                    value={prefFields.max_minutes_default}
                    onChange={(e) => setPrefFields((p) => ({ ...p, max_minutes_default: e.target.value }))}
                  />
                </label>
                <label className="label">
                  Default max calories
                  <input
                    className="input"
                    type="number"
                    min="0"
                    value={prefFields.max_calories}
                    onChange={(e) => setPrefFields((p) => ({ ...p, max_calories: e.target.value }))}
                  />
                </label>
                <label className="label">
                  Default min protein %DV
                  <input
                    className="input"
                    type="number"
                    min="0"
                    value={prefFields.min_protein_pdv}
                    onChange={(e) => setPrefFields((p) => ({ ...p, min_protein_pdv: e.target.value }))}
                  />
                </label>
                <label className="label">
                  Default max carbs %DV
                  <input
                    className="input"
                    type="number"
                    min="0"
                    value={prefFields.max_carbs_pdv}
                    onChange={(e) => setPrefFields((p) => ({ ...p, max_carbs_pdv: e.target.value }))}
                  />
                </label>
              </div>
              <button className="button" type="submit" disabled={loading}>
                Save Preferences
              </button>
            </form>

            {showDevInspector && (
              <details className="dev-details">
                <summary>Current preference payload</summary>
                <pre>{JSON.stringify(preferences, null, 2)}</pre>
              </details>
            )}
          </section>
        )}

        {appTab === "shopping" && (
          <section className="panel">
            <h2 className="panel-title">Shopping List</h2>
            <div className="inline-form">
              <label className="label">
                Plan ID
                <input
                  className="input"
                  value={selectedPlanId}
                  onChange={(e) => setSelectedPlanId(e.target.value)}
                  placeholder="Enter plan ID"
                />
              </label>
              <button
                type="button"
                className="button secondary"
                onClick={() => loadShoppingList(selectedPlanId)}
                disabled={loading || !selectedPlanId}
              >
                Load
              </button>
              <button
                type="button"
                className="button"
                onClick={() => handleGenerateShoppingList(selectedPlanId)}
                disabled={loading || !selectedPlanId}
              >
                Regenerate
              </button>
            </div>

            {!shoppingList && <p className="panel-description">Load or generate a shopping list for a meal plan.</p>}
            {shoppingList && (
              <div className="list-block">
                {(shoppingList.items || []).map((item) => (
                  <div key={item.ingredient} className="list-item compact">
                    <span>{item.ingredient}</span>
                    <strong>x{item.count}</strong>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

export default App;

import React, { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE = process.env.REACT_APP_API_BASE_URL || "http://localhost:8000/api";

const QUICK_PROMPTS = [
  "4 chicken dinners under 30 minutes",
  "3 vegetarian dinners with pasta",
  "5 high protein meals with beef",
  "4 quick meals with rice and vegetables",
  "3 healthy fish dinners",
  "4 budget-friendly vegetarian meals",
  "3 easy family dinners",
  "4 low calorie chicken meals",
  "3 tofu dinners under 40 minutes",
  "4 vegetarian meals with chickpeas",
  "5 simple dinners with potatoes",
  "4 vegetarian meals",
  "3 gluten free dinners with chicken",
  "4 dairy free meals with salmon",
  "5 easy dinners with eggs",
];

const randomQuickPrompt = () => QUICK_PROMPTS[Math.floor(Math.random() * QUICK_PROMPTS.length)];

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

const TITLE_STOP_WORDS = new Set([
  "a",
  "an",
  "and",
  "as",
  "at",
  "by",
  "for",
  "from",
  "in",
  "of",
  "on",
  "or",
  "the",
  "to",
  "with",
]);

const ACRONYM_MAP = {
  bbq: "BBQ",
  blt: "BLT",
  ai: "AI",
};

const normalizeText = (value) =>
  String(value || "")
    .replace(/\s+/g, " ")
    .replace(/\s+,/g, ",")
    .replace(/\s+\./g, ".")
    .replace(/\s+!/g, "!")
    .replace(/\s+\?/g, "?")
    .replace(/\(\s+/g, "(")
    .replace(/\s+\)/g, ")")
    .trim();

const capitalizeFirstLetter = (value) => {
  const text = normalizeText(value);
  if (!text) return "";
  const idx = text.search(/[a-zA-Z]/);
  if (idx < 0) return text;
  return `${text.slice(0, idx)}${text[idx].toUpperCase()}${text.slice(idx + 1)}`;
};

const formatRecipeTitle = (value) => {
  const text = normalizeText(value);
  if (!text) return "";
  const words = text.toLowerCase().split(" ");
  return words
    .map((word, idx) => {
      if (ACRONYM_MAP[word]) return ACRONYM_MAP[word];
      if (word.includes("'")) {
        return word
          .split("'")
          .map((part) => (part ? `${part[0].toUpperCase()}${part.slice(1)}` : part))
          .join("'");
      }
      if (TITLE_STOP_WORDS.has(word) && idx > 0 && idx < words.length - 1) {
        return word;
      }
      return `${word[0]?.toUpperCase() || ""}${word.slice(1)}`;
    })
    .join(" ");
};

const formatIngredientList = (ingredients) => {
  if (Array.isArray(ingredients)) {
    return ingredients
      .map((item) => capitalizeFirstLetter(item))
      .filter(Boolean)
      .join(", ");
  }
  return String(ingredients || "")
    .split(",")
    .map((item) => capitalizeFirstLetter(item))
    .filter(Boolean)
    .join(", ");
};

const formatInstructionStep = (step) => {
  const text = capitalizeFirstLetter(step);
  if (!text) return "";
  return /[.!?]$/.test(text) ? text : `${text}.`;
};

const toMoney = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0.00";
  return n.toFixed(2);
};

const buildShoppingListExportText = (shoppingList, planLabel = "") => {
  const items = Array.isArray(shoppingList?.items) ? shoppingList.items : [];
  const currency = shoppingList?.cost_summary?.currency || "EUR";
  const total = toMoney(shoppingList?.cost_summary?.estimated_total ?? 0);
  const notes = String(shoppingList?.cost_summary?.notes || "").trim();
  const heading = planLabel ? `Panion Shopping List - ${planLabel}` : "Panion Shopping List";

  const lines = [
    heading,
    `Estimated Total (Plan-Level Budget): ${currency} ${total}`,
    "",
    "Items",
  ];

  for (const item of items) {
    const ingredient = capitalizeFirstLetter(item?.ingredient || "Unknown item");
    lines.push(`- [ ] ${ingredient}`);
  }

  if (notes) {
    lines.push("");
    lines.push(`Notes: ${notes}`);
  }

  return lines.join("\n");
};

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
  const [inputMode, setInputMode] = useState("prompt");
  const [prompt, setPrompt] = useState(() => randomQuickPrompt());
  const [promptPrefilled, setPromptPrefilled] = useState(true);

  const [manualFields, setManualFields] = useState({
    num_meals: "4",
    ingredient_keywords: "",
    exclude_ingredients: "",
    max_minutes: "",
    max_calories: "",
    min_protein_pdv: "",
    max_carbs_pdv: "",
    max_total_budget: "",
    search_text: "",
  });
  const [useBudgetCap, setUseBudgetCap] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [optimizeMode, setOptimizeMode] = useState("balanced");
  const [showNutrition, setShowNutrition] = useState(false);

  const [parsedQuery, setParsedQuery] = useState(null);
  const [recipes, setRecipes] = useState([]);
  const [mealPlan, setMealPlan] = useState(null);
  const [savedPlans, setSavedPlans] = useState([]);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const [shoppingList, setShoppingList] = useState(null);

  const [availableTags, setAvailableTags] = useState([]);
  const [includeTags, setIncludeTags] = useState([]);
  const [excludeTags, setExcludeTags] = useState([]);
  const [includeTagDraft, setIncludeTagDraft] = useState("");
  const [excludeTagDraft, setExcludeTagDraft] = useState("");

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

  const isAdmin = Boolean(currentUser?.is_staff);

  const parserWarnings = useMemo(() => {
    if (!parsedQuery) return [];
    return Array.isArray(parsedQuery.parser_warnings) ? parsedQuery.parser_warnings : [];
  }, [parsedQuery]);

  const persistAuth = (payload) => {
    const access = payload?.access || "";
    const refresh = payload?.refresh || "";
    const user = payload?.user ||
      (payload?.email
        ? {
            id: payload.user_id,
            email: payload.email,
            is_staff: Boolean(payload.is_staff),
            is_superuser: Boolean(payload.is_superuser),
          }
        : null);

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
    setAvailableTags([]);
    setIncludeTags([]);
    setExcludeTags([]);
    setIncludeTagDraft("");
    setExcludeTagDraft("");
    setOptimizeMode("balanced");
    setUseBudgetCap(false);
    setManualFields({
      num_meals: "4",
      ingredient_keywords: "",
      exclude_ingredients: "",
      max_minutes: "",
      max_calories: "",
      min_protein_pdv: "",
      max_carbs_pdv: "",
      max_total_budget: "",
      search_text: "",
    });
    setPrompt(randomQuickPrompt());
    setPromptPrefilled(true);
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
      } catch (_parseError) {
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

  const loadTags = async () => {
    const data = await apiFetch("/tags/?limit=220");
    setAvailableTags(Array.isArray(data?.tags) ? data.tags : []);
  };

  const loadPlanDetail = async (planId) => {
    if (!planId) return;
    try {
      const data = await apiFetch(`/meal-plans/${planId}/`);
      setSelectedPlan(data);
      setSelectedPlanId(String(planId));
      setError("");
    } catch (err) {
      if (String(err.message).includes("404")) {
        setError("That meal plan was not found for this account.");
      } else {
        setError(err.message);
      }
      setSelectedPlan(null);
    }
  };

  const loadShoppingList = async (planId) => {
    if (!planId) return;
    try {
      const data = await apiFetch(`/meal-plans/${planId}/shopping-list/`);
      setShoppingList(data);
      setSelectedPlanId(String(planId));
      setError("");
    } catch (err) {
      if (String(err.message).includes("404")) {
        setError("No shopping list found for that plan in this account. Try generating one.");
      } else {
        setError(err.message);
      }
      setShoppingList(null);
    }
  };

  useEffect(() => {
    if (!accessToken) return;

    const boot = async () => {
      setError("");
      try {
        await Promise.all([loadProfile(), loadPreferences(), loadSavedPlans(), loadTags()]);
      } catch (err) {
        setError(err.message);
      }
    };

    boot();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  useEffect(() => {
    if (!isAdmin && appTab === "admin") {
      setAppTab("plan");
    }
  }, [isAdmin, appTab]);

  useEffect(() => {
    if (savedPlans.length === 0) {
      setSelectedPlanId("");
      return;
    }
    const hasSelected = savedPlans.some((plan) => String(plan.id) === String(selectedPlanId));
    if (!hasSelected) {
      setSelectedPlanId(String(savedPlans[0].id));
    }
  }, [savedPlans, selectedPlanId]);

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

  const addTagConstraint = (type) => {
    if (type === "include") {
      const tag = includeTagDraft.trim().toLowerCase();
      if (!tag) return;
      setIncludeTags((prev) => (prev.includes(tag) ? prev : [...prev, tag]));
      setExcludeTags((prev) => prev.filter((x) => x !== tag));
      setIncludeTagDraft("");
      return;
    }

    const tag = excludeTagDraft.trim().toLowerCase();
    if (!tag) return;
    setExcludeTags((prev) => (prev.includes(tag) ? prev : [...prev, tag]));
    setIncludeTags((prev) => prev.filter((x) => x !== tag));
    setExcludeTagDraft("");
  };

  const removeTagConstraint = (type, tag) => {
    if (type === "include") {
      setIncludeTags((prev) => prev.filter((x) => x !== tag));
      return;
    }
    setExcludeTags((prev) => prev.filter((x) => x !== tag));
  };

  const buildGeneratePayload = () => {
    if (inputMode === "manual") {
      return {
        input_mode: "manual",
        optimize_mode: optimizeMode,
        manual_query: {
          num_meals: Number(manualFields.num_meals || 3),
          ingredient_keywords: fromCsv(manualFields.ingredient_keywords),
          include_tags: includeTags,
          exclude_tags: excludeTags,
          exclude_ingredients: fromCsv(manualFields.exclude_ingredients),
          max_minutes: manualFields.max_minutes === "" ? null : Number(manualFields.max_minutes),
          max_calories: manualFields.max_calories === "" ? null : Number(manualFields.max_calories),
          min_protein_pdv: manualFields.min_protein_pdv === "" ? null : Number(manualFields.min_protein_pdv),
          max_carbs_pdv: manualFields.max_carbs_pdv === "" ? null : Number(manualFields.max_carbs_pdv),
          max_total_budget:
            useBudgetCap && manualFields.max_total_budget !== ""
              ? Number(manualFields.max_total_budget)
              : null,
          search_text: String(manualFields.search_text || "").trim().toLowerCase(),
        },
      };
    }

    return {
      input_mode: "prompt",
      prompt,
      include_tags: includeTags,
      exclude_tags: excludeTags,
      optimize_mode: optimizeMode,
      max_total_budget:
        useBudgetCap && manualFields.max_total_budget !== ""
          ? Number(manualFields.max_total_budget)
          : null,
    };
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
        body: buildGeneratePayload(),
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
      if (String(err.message).includes("404")) {
        setError("That meal plan does not belong to this account.");
      } else {
        setError(err.message);
      }
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

  const handleSwapGeneratedMeal = async (position) => {
    if (!mealPlan?.id) return;
    setLoading(true);
    setError("");
    setNotice("");

    try {
      const data = await apiFetch(`/meal-plans/${mealPlan.id}/swap/`, {
        method: "POST",
        body: { position },
      });
      if (data?.recipe) {
        setRecipes((prev) =>
          prev.map((recipe, idx) => (idx === position - 1 ? data.recipe : recipe))
        );
      }
      setNotice(`Swapped generated meal at position ${position}.`);
      if (selectedPlanId === String(mealPlan.id)) {
        await loadPlanDetail(mealPlan.id);
      }
      await loadSavedPlans();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRateMeal = async (position, rating) => {
    if (!selectedPlan?.id) return;
    setLoading(true);
    setError("");
    setNotice("");

    try {
      const data = await apiFetch(`/meal-plans/${selectedPlan.id}/rate/`, {
        method: "POST",
        body: { position, rating },
      });
      setSelectedPlan(data);
      setNotice(`Rated meal #${position} as ${rating} star${rating === 1 ? "" : "s"}.`);
      await loadSavedPlans();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleCopyShoppingList = async () => {
    if (!shoppingList) return;
    const selectedPlanLabel =
      savedPlans.find((plan) => String(plan.id) === String(selectedPlanId))?.title || `Plan ${selectedPlanId}`;
    const exportText = buildShoppingListExportText(shoppingList, selectedPlanLabel);

    try {
      await navigator.clipboard.writeText(exportText);
      setNotice("Shopping list copied. Paste it into Notes or your preferred app.");
      setError("");
    } catch (_err) {
      try {
        const textArea = document.createElement("textarea");
        textArea.value = exportText;
        textArea.style.position = "fixed";
        textArea.style.opacity = "0";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand("copy");
        document.body.removeChild(textArea);
        setNotice("Shopping list copied. Paste it into Notes or your preferred app.");
        setError("");
      } catch (_fallbackErr) {
        setError("Could not copy automatically. Please copy manually.");
      }
    }
  };

  const handlePromptFocus = () => {
    if (!promptPrefilled) return;
    setPrompt("");
    setPromptPrefilled(false);
  };

  const handlePromptChange = (value) => {
    setPrompt(value);
    setPromptPrefilled(false);
  };

  const handleNewSuggestion = () => {
    setPrompt(randomQuickPrompt());
    setPromptPrefilled(true);
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

  const renderTagControls = () => (
    <div className="filter-grid">
      <label className="label">
        Include tag
        <div className="inline-control">
          <select
            className="input"
            value={includeTagDraft}
            onChange={(e) => setIncludeTagDraft(e.target.value)}
          >
            <option value="">Select tag</option>
            {availableTags.map((tag) => (
              <option key={`inc-${tag}`} value={tag}>
                {tag}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="button secondary"
            onClick={() => addTagConstraint("include")}
          >
            Add
          </button>
        </div>
      </label>

      <label className="label">
        Exclude tag
        <div className="inline-control">
          <select
            className="input"
            value={excludeTagDraft}
            onChange={(e) => setExcludeTagDraft(e.target.value)}
          >
            <option value="">Select tag</option>
            {availableTags.map((tag) => (
              <option key={`exc-${tag}`} value={tag}>
                {tag}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="button secondary"
            onClick={() => addTagConstraint("exclude")}
          >
            Add
          </button>
        </div>
      </label>

      <div className="summary-row">
        <span className="summary-key">Include tags</span>
        <div className="chips-row">
          {includeTags.length === 0 && <span className="chip muted">none</span>}
          {includeTags.map((tag) => (
            <button
              key={`inc-chip-${tag}`}
              type="button"
              className="chip removable"
              onClick={() => removeTagConstraint("include", tag)}
            >
              {tag} x
            </button>
          ))}
        </div>
      </div>

      <div className="summary-row">
        <span className="summary-key">Exclude tags</span>
        <div className="chips-row">
          {excludeTags.length === 0 && <span className="chip muted">none</span>}
          {excludeTags.map((tag) => (
            <button
              key={`exc-chip-${tag}`}
              type="button"
              className="chip removable danger-chip"
              onClick={() => removeTagConstraint("exclude", tag)}
            >
              {tag} x
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  const parsedSummary = (
    <div className="summary-block">
      <div className="summary-row"><span className="summary-key">Meals</span><span>{parsedQuery?.num_meals ?? "none"}</span></div>
      <div className="summary-row"><span className="summary-key">Ingredients</span><span>{toCsv(parsedQuery?.ingredient_keywords) || "none"}</span></div>
      <div className="summary-row"><span className="summary-key">Include tags</span><span>{toCsv(parsedQuery?.include_tags) || "none"}</span></div>
      <div className="summary-row"><span className="summary-key">Exclude tags</span><span>{toCsv(parsedQuery?.exclude_tags) || "none"}</span></div>
      <div className="summary-row"><span className="summary-key">Exclude ingredients</span><span>{toCsv(parsedQuery?.exclude_ingredients) || "none"}</span></div>
      <div className="summary-row"><span className="summary-key">Max minutes</span><span>{parsedQuery?.max_minutes ?? "none"}</span></div>
      <div className="summary-row"><span className="summary-key">Max calories</span><span>{parsedQuery?.max_calories ?? "none"}</span></div>
      <div className="summary-row"><span className="summary-key">Min protein %DV</span><span>{parsedQuery?.min_protein_pdv ?? "none"}</span></div>
      <div className="summary-row"><span className="summary-key">Max carbs %DV</span><span>{parsedQuery?.max_carbs_pdv ?? "none"}</span></div>
      <div className="summary-row"><span className="summary-key">Budget cap (EUR)</span><span>{parsedQuery?.budget_cap ?? parsedQuery?.max_total_budget ?? "none"}</span></div>
      <div className="summary-row"><span className="summary-key">Estimated total (EUR)</span><span>{parsedQuery?.estimated_total ?? "none"}</span></div>
      <div className="summary-row"><span className="summary-key">Budget status</span><span>{parsedQuery?.within_budget === false ? "over budget" : parsedQuery?.budget_cap != null ? "within budget" : "no cap"}</span></div>
      <div className="summary-row"><span className="summary-key">Mode</span><span>{parsedQuery?.input_mode || inputMode}</span></div>
      <div className="summary-row"><span className="summary-key">Parser</span><span>{parsedQuery?.parser_source || "rules"}</span></div>
      <div className="summary-row"><span className="summary-key">Optimization</span><span>{parsedQuery?.optimize_mode || optimizeMode}</span></div>
    </div>
  );

  const budgetCapValue = parsedQuery?.budget_cap;
  const showBudgetStatus = budgetCapValue !== null && budgetCapValue !== undefined;

  if (!accessToken) {
    return (
      <div className="page auth-page">
        <div className="auth-card">
          <div className="brand-row">
            <img src="/PanionLogo.png" alt="Panion logo" className="logo" />
            <h1>Panion</h1>
          </div>
          <p className="hero-copy">Sign in to create, save, and manage meal plans.</p>

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

          {error && <p className="error-banner">{error}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="app-header">
        <div className="brand-row">
          <img src="/PanionLogo.png" alt="Panion logo" className="logo" />
          <div>
            <h1 className="title">Panion</h1>
            <p className="subtitle">Meal planning with prompt + manual criteria, saved plans, and shopping lists.</p>
          </div>
        </div>
        <div className="user-actions">
          <span className="chip user-chip">{currentUser?.email}</span>
          <span className={`chip role-chip ${isAdmin ? "admin-role" : "user-role"}`}>{isAdmin ? "Admin" : "User"}</span>
          <button type="button" className="button secondary" onClick={clearAuth}>Logout</button>
        </div>
      </header>

      <nav className="tabs">
        {[
          ["plan", "Plan"],
          ["saved", "Saved Plans"],
          ["preferences", "Preferences"],
          ["shopping", "Shopping List"],
          ...(isAdmin ? [["admin", "Admin"]] : []),
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`tab-btn ${appTab === key ? "active" : ""}`}
            onClick={() => setAppTab(key)}
          >
            {label}
          </button>
        ))}
      </nav>

      {(error || notice) && (
        <div className="status-strip">
          {error && <span className="error-banner">{error}</span>}
          {notice && <span className="ok-banner">{notice}</span>}
        </div>
      )}

      {appTab === "plan" && (
        <div className={`layout-grid ${!isAdmin ? "user-plan-layout" : ""}`}>
          {isAdmin ? (
            <>
              <section className="panel">
                <h2 className="panel-title">Generate Meal Plan</h2>
                <form className="form" onSubmit={handleGeneratePlan}>
                  <div className="mode-switch">
                    <button
                      type="button"
                      className={`button secondary ${inputMode === "prompt" ? "active-mode" : ""}`}
                      onClick={() => setInputMode("prompt")}
                    >
                      Prompt
                    </button>
                    <button
                      type="button"
                      className={`button secondary ${inputMode === "manual" ? "active-mode" : ""}`}
                      onClick={() => setInputMode("manual")}
                    >
                      Manual Criteria
                    </button>
                  </div>

                  {inputMode === "prompt" ? (
                    <>
                      <label className="label">
                        Prompt
                        <textarea className="textarea" value={prompt} onChange={(e) => handlePromptChange(e.target.value)} />
                      </label>
                      <label className="inline-checkbox">
                        <input
                          type="checkbox"
                          checked={useBudgetCap}
                          onChange={(e) => setUseBudgetCap(e.target.checked)}
                        />
                        Use budget cap
                      </label>
                      {useBudgetCap && (
                        <label className="label">
                          Max total budget (EUR)
                          <input
                            className="input"
                            type="number"
                            min="0"
                            step="0.5"
                            value={manualFields.max_total_budget}
                            onChange={(e) => setManualFields((p) => ({ ...p, max_total_budget: e.target.value }))}
                          />
                        </label>
                      )}
                      <div className="quick-prompts">
                        {QUICK_PROMPTS.slice(0, 6).map((x) => (
                          <button key={x} type="button" className="quick-prompt" onClick={() => handlePromptChange(x)}>
                            {x}
                          </button>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="filter-grid">
                      <label className="label">
                        Meals
                        <input
                          className="input"
                          type="number"
                          min="1"
                          max="10"
                          value={manualFields.num_meals}
                          onChange={(e) => setManualFields((p) => ({ ...p, num_meals: e.target.value }))}
                        />
                      </label>
                      <label className="label">
                        Ingredients (comma-separated)
                        <input
                          className="input"
                          value={manualFields.ingredient_keywords}
                          onChange={(e) => setManualFields((p) => ({ ...p, ingredient_keywords: e.target.value }))}
                        />
                      </label>
                      <label className="label">
                        Exclude ingredients (comma-separated)
                        <input
                          className="input"
                          value={manualFields.exclude_ingredients}
                          onChange={(e) => setManualFields((p) => ({ ...p, exclude_ingredients: e.target.value }))}
                        />
                      </label>
                      <label className="label">
                        Search text
                        <input
                          className="input"
                          value={manualFields.search_text}
                          onChange={(e) => setManualFields((p) => ({ ...p, search_text: e.target.value }))}
                        />
                      </label>
                      <label className="label">
                        Max minutes
                        <input
                          className="input"
                          type="number"
                          min="1"
                          value={manualFields.max_minutes}
                          onChange={(e) => setManualFields((p) => ({ ...p, max_minutes: e.target.value }))}
                        />
                      </label>
                      <label className="label">
                        Max calories
                        <input
                          className="input"
                          type="number"
                          min="0"
                          value={manualFields.max_calories}
                          onChange={(e) => setManualFields((p) => ({ ...p, max_calories: e.target.value }))}
                        />
                      </label>
                      <label className="label">
                        Min protein %DV
                        <input
                          className="input"
                          type="number"
                          min="0"
                          value={manualFields.min_protein_pdv}
                          onChange={(e) => setManualFields((p) => ({ ...p, min_protein_pdv: e.target.value }))}
                        />
                      </label>
                      <label className="label">
                        Max carbs %DV
                        <input
                          className="input"
                          type="number"
                          min="0"
                          value={manualFields.max_carbs_pdv}
                          onChange={(e) => setManualFields((p) => ({ ...p, max_carbs_pdv: e.target.value }))}
                        />
                      </label>
                      <label className="inline-checkbox">
                        <input
                          type="checkbox"
                          checked={useBudgetCap}
                          onChange={(e) => setUseBudgetCap(e.target.checked)}
                        />
                        Use budget cap
                      </label>
                      {useBudgetCap && (
                        <label className="label">
                          Max total budget (EUR)
                          <input
                            className="input"
                            type="number"
                            min="0"
                            step="0.5"
                            value={manualFields.max_total_budget}
                            onChange={(e) => setManualFields((p) => ({ ...p, max_total_budget: e.target.value }))}
                          />
                        </label>
                      )}
                    </div>
                  )}

                  <label className="label">
                    Optimization mode
                    <select
                      className="input"
                      value={optimizeMode}
                      onChange={(e) => setOptimizeMode(e.target.value)}
                    >
                      <option value="balanced">Balanced</option>
                      <option value="budget">Budget-first</option>
                      <option value="sustainability">Sustainability-first</option>
                    </select>
                  </label>

                  {renderTagControls()}

                  <div className="toggle-row">
                    <button className="button cta-button" type="submit" disabled={loading}>
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
                      onClick={() => setAppTab("admin")}
                    >
                      Open Admin Tools
                    </button>
                  </div>
                </form>
              </section>

              <section className="panel">
                <h2 className="panel-title">Parsed Request</h2>
                {!parsedQuery && <p className="panel-description">Generate a plan to inspect parsed criteria.</p>}
                {parsedQuery && parsedSummary}

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
              </section>
            </>
          ) : (
            <section className="panel panel-wide user-chat-panel">
              <h2 className="panel-title">Plan Meals With Chat</h2>
              <p className="panel-description">Describe your meals and generate a full plan.</p>
              <form className="form user-chat-form" onSubmit={handleGeneratePlan}>
                <div className="mode-switch compact-toggle">
                  <button
                    type="button"
                    className={`button secondary compact-toggle-btn ${inputMode === "prompt" ? "active-mode" : ""}`}
                    onClick={() => setInputMode("prompt")}
                  >
                    Prompt
                  </button>
                  <button
                    type="button"
                    className={`button secondary compact-toggle-btn ${inputMode === "manual" ? "active-mode" : ""}`}
                    onClick={() => setInputMode("manual")}
                  >
                    Manual
                  </button>
                </div>

                {inputMode === "prompt" ? (
                  <>
                    <label className="label">
                      Chat
                      <textarea
                        className="textarea chat-input"
                        value={prompt}
                        onFocus={handlePromptFocus}
                        onChange={(e) => handlePromptChange(e.target.value)}
                      />
                    </label>
                    <label className="inline-checkbox">
                      <input
                        type="checkbox"
                        checked={useBudgetCap}
                        onChange={(e) => setUseBudgetCap(e.target.checked)}
                      />
                      Use budget cap
                    </label>
                    {useBudgetCap && (
                      <label className="label narrow-label">
                        Max total budget (EUR)
                        <input
                          className="input"
                          type="number"
                          min="0"
                          step="0.5"
                          value={manualFields.max_total_budget}
                          onChange={(e) => setManualFields((p) => ({ ...p, max_total_budget: e.target.value }))}
                        />
                      </label>
                    )}
                    <div className="suggestion-row">
                      <span className="panel-description">{promptPrefilled ? "Suggestion loaded" : "Type your own request"}</span>
                      <button type="button" className="button secondary" onClick={handleNewSuggestion}>
                        New Suggestion
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="filter-grid">
                    <label className="label">
                      Meals
                      <input
                        className="input"
                        type="number"
                        min="1"
                        max="10"
                        value={manualFields.num_meals}
                        onChange={(e) => setManualFields((p) => ({ ...p, num_meals: e.target.value }))}
                      />
                    </label>
                    <label className="label">
                      Ingredients (comma-separated)
                      <input
                        className="input"
                        value={manualFields.ingredient_keywords}
                        onChange={(e) => setManualFields((p) => ({ ...p, ingredient_keywords: e.target.value }))}
                      />
                    </label>
                    <label className="label">
                      Exclude ingredients (comma-separated)
                      <input
                        className="input"
                        value={manualFields.exclude_ingredients}
                        onChange={(e) => setManualFields((p) => ({ ...p, exclude_ingredients: e.target.value }))}
                      />
                    </label>
                    <label className="label">
                      Search text
                      <input
                        className="input"
                        value={manualFields.search_text}
                        onChange={(e) => setManualFields((p) => ({ ...p, search_text: e.target.value }))}
                      />
                    </label>
                    <label className="label">
                      Max minutes
                      <input
                        className="input"
                        type="number"
                        min="1"
                        value={manualFields.max_minutes}
                        onChange={(e) => setManualFields((p) => ({ ...p, max_minutes: e.target.value }))}
                      />
                    </label>
                    <label className="label">
                      Max calories
                      <input
                        className="input"
                        type="number"
                        min="0"
                        value={manualFields.max_calories}
                        onChange={(e) => setManualFields((p) => ({ ...p, max_calories: e.target.value }))}
                      />
                    </label>
                    <label className="label">
                      Min protein %DV
                      <input
                        className="input"
                        type="number"
                        min="0"
                        value={manualFields.min_protein_pdv}
                        onChange={(e) => setManualFields((p) => ({ ...p, min_protein_pdv: e.target.value }))}
                      />
                    </label>
                    <label className="label">
                      Max carbs %DV
                      <input
                        className="input"
                        type="number"
                        min="0"
                        value={manualFields.max_carbs_pdv}
                        onChange={(e) => setManualFields((p) => ({ ...p, max_carbs_pdv: e.target.value }))}
                      />
                    </label>
                    <label className="inline-checkbox">
                      <input
                        type="checkbox"
                        checked={useBudgetCap}
                        onChange={(e) => setUseBudgetCap(e.target.checked)}
                      />
                      Use budget cap
                    </label>
                    {useBudgetCap && (
                      <label className="label">
                        Max total budget (EUR)
                        <input
                          className="input"
                          type="number"
                          min="0"
                          step="0.5"
                          value={manualFields.max_total_budget}
                          onChange={(e) => setManualFields((p) => ({ ...p, max_total_budget: e.target.value }))}
                        />
                      </label>
                    )}
                  </div>
                )}

                <label className="label narrow-label">
                  Optimization mode
                  <select
                    className="input"
                    value={optimizeMode}
                    onChange={(e) => setOptimizeMode(e.target.value)}
                  >
                    <option value="balanced">Balanced</option>
                    <option value="budget">Budget-first</option>
                    <option value="sustainability">Sustainability-first</option>
                  </select>
                </label>
                {inputMode === "manual" && renderTagControls()}

                <div className="toggle-row user-chat-actions">
                  <button className="button cta-button" type="submit" disabled={loading}>
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
                </div>
              </form>

              {parsedQuery && (
                <details className="dev-details parsed-dropdown">
                  <summary>Show Parsed Info (optional)</summary>
                  {parsedSummary}
                  {parserWarnings.length > 0 && (
                    <div className="warning-panel">
                      <strong>Warnings</strong>
                      <ul>
                        {parserWarnings.map((w, i) => (
                          <li key={`${w}-parsed-${i}`}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </details>
              )}
            </section>
          )}

          <section className="panel panel-wide">
            <h2 className="panel-title">Recipes</h2>
            {mealPlan?.id && (
              <p className="panel-description">Hover a recipe card and click to swap that meal.</p>
            )}
            {showBudgetStatus && (
              <div className={`budget-status ${parsedQuery?.within_budget === false ? "over" : "within"}`}>
                <strong>
                  {parsedQuery?.within_budget === false ? "Over budget" : "Within budget"}:
                </strong>{" "}
                cap EUR {parsedQuery?.budget_cap} | est EUR {parsedQuery?.estimated_total ?? "0.00"}
                {parsedQuery?.budget_overrun > 0 && (
                  <span> | overrun EUR {parsedQuery.budget_overrun}</span>
                )}
                {parsedQuery?.budget_warning && (
                  <div className="panel-description">{parsedQuery.budget_warning}</div>
                )}
              </div>
            )}
            {!recipes.length && <p className="panel-description">No recipes yet.</p>}
            <div className="recipe-grid">
              {recipes.map((recipe, idx) => (
                <article
                  key={recipe.id}
                  className={`recipe-card ${mealPlan?.id ? "generated-swappable" : ""}`}
                  onClick={mealPlan?.id ? () => handleSwapGeneratedMeal(idx + 1) : undefined}
                  onKeyDown={
                    mealPlan?.id
                      ? (e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            handleSwapGeneratedMeal(idx + 1);
                          }
                        }
                      : undefined
                  }
                  role={mealPlan?.id ? "button" : undefined}
                  tabIndex={mealPlan?.id ? 0 : undefined}
                  title={mealPlan?.id ? `Swap meal #${idx + 1}` : undefined}
                >
                  <h3 className="recipe-title">{formatRecipeTitle(recipe.name)}</h3>
                  <div className="recipe-meta">
                    <span className="chip">{recipe.minutes || "?"} min</span>
                    <span className="chip">{recipe.n_ingredients ?? "?"} ingredients</span>
                    <span className="chip">{recipe.n_steps ?? "?"} steps</span>
                  </div>
                  <p className="recipe-copy"><strong>Ingredients:</strong> {formatIngredientList(recipe.ingredients)}</p>
                  <div className="recipe-copy">
                    <strong>Instructions:</strong>
                    {Array.isArray(recipe.instructions) && recipe.instructions.length > 0 ? (
                      <ol>
                        {recipe.instructions.map((step, idx) => (
                          <li key={`${recipe.id}-${idx}`}>{formatInstructionStep(step)}</li>
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
                    <div className="panel-description">
                      {plan.is_completed ? "Completed" : "In progress"} | Rated {plan.rated_count ?? 0}/{plan.total_count ?? plan.item_count ?? 0}
                    </div>
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
                <p className="panel-description">
                  {selectedPlan.is_completed ? "Completed plan" : "Plan in progress"} | Rated {selectedPlan.rated_count ?? 0}/{selectedPlan.total_count ?? (selectedPlan.items || []).length}
                </p>
                <div className="list-block">
                  {(selectedPlan.items || []).map((item) => (
                    <div key={item.position} className="list-item compact">
                      <div>
                        <strong>#{item.position}</strong> {item.recipe_name}
                        <div className="row-actions" style={{ marginTop: 6 }}>
                          {[1, 2, 3, 4, 5].map((star) => (
                            <button
                              key={`${item.position}-${star}`}
                              type="button"
                              className={`button secondary ${item.rating === star ? "active-mode" : ""}`}
                              onClick={() => handleRateMeal(item.position, star)}
                              disabled={loading}
                            >
                              {star}*
                            </button>
                          ))}
                        </div>
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

        </section>
      )}

      {appTab === "shopping" && (
        <section className="panel">
          <h2 className="panel-title">Shopping List</h2>
          <div className="inline-form">
            <label className="label">
              Meal plan
              <select
                className="input"
                value={selectedPlanId}
                onChange={(e) => setSelectedPlanId(e.target.value)}
              >
                {savedPlans.length === 0 && <option value="">No plans available</option>}
                {savedPlans.map((plan) => (
                  <option key={`shop-plan-${plan.id}`} value={plan.id}>
                    {plan.title} (ID {plan.id})
                  </option>
                ))}
              </select>
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
            <div className="list-block shopping-list-shell">
              <div className="shopping-toolbar">
                <span className="panel-description">Copy as clean checklist for Notes/Reminders.</span>
                <button type="button" className="button secondary" onClick={handleCopyShoppingList}>
                  Copy List
                </button>
              </div>

              <div className="list-item shopping-summary-card">
                <div>
                  <strong>Estimated Total (Plan-Level Budget)</strong>
                  {shoppingList.cost_summary?.notes && (
                    <div className="panel-description">{shoppingList.cost_summary.notes}</div>
                  )}
                </div>
                <strong>
                  {shoppingList.cost_summary?.currency || "EUR"} {shoppingList.cost_summary?.estimated_total ?? "0.00"}
                </strong>
              </div>
              {(shoppingList.items || []).map((item, idx) => (
                <div key={`${item.ingredient}-${idx}`} className="list-item compact shopping-item-row">
                  <div className="shopping-item-main">
                    <span className="shopping-check">[ ]</span>
                    <span className="shopping-ingredient">{capitalizeFirstLetter(item.ingredient)}</span>
                  </div>
                  <div className="shopping-item-meta">
                    {Array.isArray(item.variants) && item.variants.length > 1 && (
                      <div className="panel-description">From: {item.variants.join(", ")}</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {isAdmin && appTab === "admin" && (
        <div className="layout-grid two-col">
          <section className="panel">
            <h2 className="panel-title">Admin Diagnostics</h2>
            <p className="panel-description">Developer-level diagnostics for parser and generation flow.</p>
            <div className="summary-block">
              <div className="summary-row"><span className="summary-key">Current user</span><span>{currentUser?.email || "none"}</span></div>
              <div className="summary-row"><span className="summary-key">Role</span><span>{currentUser?.is_superuser ? "superuser" : "staff"}</span></div>
              <div className="summary-row"><span className="summary-key">Latest input mode</span><span>{parsedQuery?.input_mode || "none"}</span></div>
              <div className="summary-row"><span className="summary-key">Latest parser</span><span>{parsedQuery?.parser_source || "none"}</span></div>
              <div className="summary-row"><span className="summary-key">Warnings</span><span>{parserWarnings.length}</span></div>
              <div className="summary-row"><span className="summary-key">Saved plans</span><span>{savedPlans.length}</span></div>
            </div>
          </section>

          <section className="panel">
            <h2 className="panel-title">Inspector Panels</h2>
            <details className="dev-details" open>
              <summary>Parsed query payload</summary>
              <pre>{JSON.stringify(parsedQuery || { note: "No parsed request yet" }, null, 2)}</pre>
            </details>
            <details className="dev-details">
              <summary>Optimizer fallback payload</summary>
              <pre>{JSON.stringify(parsedQuery?.fallback || { note: "No fallback payload yet" }, null, 2)}</pre>
            </details>
            <details className="dev-details">
              <summary>Current preference payload</summary>
              <pre>{JSON.stringify(preferences, null, 2)}</pre>
            </details>
            <details className="dev-details">
              <summary>Selected plan payload</summary>
              <pre>{JSON.stringify(selectedPlan || { note: "No selected plan" }, null, 2)}</pre>
            </details>
          </section>
        </div>
      )}

    </div>
  );
}

export default App;

#!/usr/bin/env python3
import csv
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "http://localhost:8000/api"
REPORT_DIR = Path("reports/budget_test_campaign")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _request(path, method="GET", data=None, token=None):
    url = f"{API_BASE}{path}"
    body = None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            elapsed_ms = int((time.time() - started) * 1000)
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            return resp.status, payload, elapsed_ms, None
    except urllib.error.HTTPError as e:
        elapsed_ms = int((time.time() - started) * 1000)
        text = e.read().decode("utf-8") if e.fp else ""
        try:
            payload = json.loads(text) if text else {}
        except Exception:
            payload = {"raw": text}
        return e.code, payload, elapsed_ms, f"HTTP {e.code}"
    except Exception as e:
        elapsed_ms = int((time.time() - started) * 1000)
        return 0, {}, elapsed_ms, str(e)


def _build_manual_case(case_id, *, num_meals, ingredient_keywords=None, include_tags=None, exclude_ingredients=None,
                       max_minutes=None, max_calories=None, max_total_budget=None):
    ingredient_keywords = ingredient_keywords or []
    include_tags = include_tags or []
    exclude_ingredients = exclude_ingredients or []
    return {
        "case_id": case_id,
        "mode": "manual",
        "input_mode": "manual",
        "optimize_mode": "budget",
        "manual_query": {
            "num_meals": num_meals,
            "ingredient_keywords": ingredient_keywords,
            "include_tags": include_tags,
            "exclude_tags": [],
            "exclude_ingredients": exclude_ingredients,
            "max_minutes": max_minutes,
            "max_calories": max_calories,
            "min_protein_pdv": None,
            "max_carbs_pdv": None,
            "max_total_budget": max_total_budget,
            "search_text": "",
        },
    }


def _build_prompt_case(case_id, prompt):
    return {
        "case_id": case_id,
        "mode": "prompt",
        "input_mode": "prompt",
        "prompt": prompt,
        "optimize_mode": "balanced",
        "include_tags": [],
        "exclude_tags": [],
    }


def _cases():
    return [
        _build_prompt_case(1, "Create 4 vegetarian dinners under 45 minutes"),
        _build_prompt_case(2, "Give me 4 chicken dinners under 30 minutes"),
        _build_prompt_case(3, "Create 3 chicken meals under 45 minutes"),
        _build_prompt_case(4, "Make 4 healthy dinners without fish"),

        _build_manual_case(5, num_meals=4, ingredient_keywords=["chicken"], max_minutes=45, max_total_budget=40),
        _build_manual_case(6, num_meals=4, ingredient_keywords=["chicken"], max_minutes=45, max_total_budget=25),
        _build_manual_case(7, num_meals=4, ingredient_keywords=["chicken"], max_minutes=45, max_total_budget=12),
        _build_manual_case(8, num_meals=4, include_tags=["vegetarian"], max_minutes=45, max_total_budget=20),
        _build_manual_case(9, num_meals=4, include_tags=["vegetarian"], max_minutes=45, max_total_budget=10),
        _build_manual_case(10, num_meals=5, ingredient_keywords=["rice"], max_minutes=60, max_total_budget=18),

        _build_manual_case(11, num_meals=4, ingredient_keywords=["chicken"], exclude_ingredients=["fish", "seed"], max_total_budget=22),
        _build_manual_case(12, num_meals=4, include_tags=["low-carb"], max_minutes=40, max_total_budget=25),
        _build_manual_case(13, num_meals=4, include_tags=["healthy"], max_calories=600, max_total_budget=30),
        _build_manual_case(14, num_meals=4, ingredient_keywords=["beef"], max_minutes=35, max_total_budget=20),

        _build_manual_case(15, num_meals=4, ingredient_keywords=["beef"], max_minutes=30, max_total_budget=6),
        _build_manual_case(16, num_meals=6, include_tags=["vegetarian"], max_minutes=30, max_total_budget=8),

        _build_manual_case(17, num_meals=4, ingredient_keywords=["chicken"], max_minutes=45, max_total_budget=None),
        _build_manual_case(18, num_meals=4, include_tags=["vegetarian"], max_minutes=45, max_total_budget=None),
    ]


def _assertions(case, status, data):
    checks = []
    notes = []

    checks.append(status == 200)
    if status != 200:
        return False, ["status_not_200"]

    recipes = data.get("recipes") or []
    query = data.get("query") or {}
    no_results = bool(data.get("no_results"))
    checks.append(isinstance(query.get("fallback"), dict))

    # For this campaign, all cases are intended to return recipes.
    checks.append(not no_results)
    checks.append(len(recipes) > 0)

    if case["mode"] == "prompt":
        checks.append(query.get("parser_source") in {"rules", "openai"})

    if case["mode"] == "manual":
        cap_sent = case["manual_query"].get("max_total_budget")
        cap_resp = query.get("budget_cap")
        within = query.get("within_budget")
        est_total = query.get("estimated_total")
        warning = str(query.get("budget_warning") or "").strip()
        overrun = query.get("budget_overrun")

        checks.append(est_total is not None)
        checks.append(isinstance(within, bool))

        if cap_sent is None:
            checks.append(cap_resp is None)
        else:
            checks.append(cap_resp is not None)
            if within is True:
                checks.append(float(est_total) <= float(cap_resp) + 0.01)
            else:
                checks.append(bool(warning))
                checks.append(float(overrun or 0) > 0)

    # Special exclusion check for case 11
    if case["case_id"] == 11:
        for recipe in recipes:
            ing = " ".join((recipe.get("ingredients") or [])).lower()
            checks.append("fish" not in ing)
            checks.append("seed" not in ing)

    if not all(checks):
        notes.append("assertion_failed")
    return all(checks), notes


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    email = f"budgettest_{timestamp}@panion.local"
    password = "BudgetTest123!"

    # Register user
    _request(
        "/auth/register/",
        method="POST",
        data={"email": email, "password": password, "confirm_password": password},
    )

    status, login_payload, _, err = _request(
        "/auth/login/",
        method="POST",
        data={"email": email, "password": password},
    )
    if status != 200 or not login_payload.get("access"):
        raise SystemExit(f"Login failed: status={status} err={err} payload={login_payload}")
    token = login_payload["access"]

    rows = []
    within_example = None
    over_example = None

    for case in _cases():
        payload = {
            "input_mode": case["input_mode"],
            "optimize_mode": case["optimize_mode"],
        }
        if case["input_mode"] == "prompt":
            payload["prompt"] = case["prompt"]
            payload["include_tags"] = case.get("include_tags", [])
            payload["exclude_tags"] = case.get("exclude_tags", [])
            case_text = case["prompt"]
            budget_cap = ""
        else:
            payload["manual_query"] = case["manual_query"]
            case_text = json.dumps(case["manual_query"], ensure_ascii=False)
            budget_cap = case["manual_query"].get("max_total_budget")

        status, data, elapsed_ms, err = _request(
            "/meal-plans/generate/",
            method="POST",
            data=payload,
            token=token,
        )

        passed, notes = _assertions(case, status, data)
        query = data.get("query") if isinstance(data, dict) else {}
        recipes = data.get("recipes") if isinstance(data, dict) else []
        result_count = len(recipes) if isinstance(recipes, list) else 0
        estimated_total = query.get("estimated_total") if isinstance(query, dict) else None
        within_budget = query.get("within_budget") if isinstance(query, dict) else None
        warning = str((query or {}).get("budget_warning") or "") if isinstance(query, dict) else ""

        row = {
            "case_id": case["case_id"],
            "mode": case["mode"],
            "prompt/manual_query": case_text,
            "budget_cap": budget_cap if budget_cap is not None else "",
            "result_count": result_count,
            "estimated_total": estimated_total if estimated_total is not None else "",
            "within_budget": within_budget if within_budget is not None else "",
            "warning": warning,
            "status_code": status,
            "duration_ms": elapsed_ms,
            "pass/fail": "PASS" if passed else "FAIL",
            "notes": ";".join(notes + ([err] if err else [])),
        }
        rows.append(row)

        if isinstance(query, dict) and case["mode"] == "manual" and case["manual_query"].get("max_total_budget") is not None:
            if within_example is None and query.get("within_budget") is True:
                within_example = {"case": case["case_id"], "request": payload, "response": data}
            if over_example is None and query.get("within_budget") is False:
                over_example = {"case": case["case_id"], "request": payload, "response": data}

    csv_path = REPORT_DIR / "budget_test_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case_id",
                "mode",
                "prompt/manual_query",
                "budget_cap",
                "result_count",
                "estimated_total",
                "within_budget",
                "warning",
                "status_code",
                "duration_ms",
                "pass/fail",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    budget_on = [r for r in rows if str(r["budget_cap"]).strip() != ""]
    feasible_ids = {5, 6, 8, 10, 11, 12, 13, 14}
    strict_ids = {15, 16}

    feasible_rows = [r for r in rows if r["case_id"] in feasible_ids]
    strict_rows = [r for r in rows if r["case_id"] in strict_ids]

    feasible_within = sum(1 for r in feasible_rows if str(r["within_budget"]).lower() == "true")
    feasible_pct = (feasible_within / len(feasible_rows) * 100.0) if feasible_rows else 0.0

    strict_overwarn = sum(
        1
        for r in strict_rows
        if str(r["within_budget"]).lower() == "false" and bool(str(r["warning"]).strip())
    )
    strict_pct = (strict_overwarn / len(strict_rows) * 100.0) if strict_rows else 0.0

    overruns = []
    for r in budget_on:
        if str(r["within_budget"]).lower() == "false":
            try:
                # pull overrun from warning response by reusing saved rows not available here
                pass
            except Exception:
                pass

    # Re-run parse for overrun directly from saved evidence rows impossible here; use available estimate-cap delta.
    for r in budget_on:
        if str(r["within_budget"]).lower() == "false":
            try:
                cap = float(r["budget_cap"])
                est = float(r["estimated_total"])
                overruns.append(max(0.0, est - cap))
            except Exception:
                continue

    avg_overrun = (sum(overruns) / len(overruns)) if overruns else 0.0
    pass_count = sum(1 for r in rows if r["pass/fail"] == "PASS")

    if within_example:
        (REPORT_DIR / "evidence_within_budget.json").write_text(json.dumps(within_example, indent=2), encoding="utf-8")
    if over_example:
        (REPORT_DIR / "evidence_over_budget.json").write_text(json.dumps(over_example, indent=2), encoding="utf-8")

    summary_md = REPORT_DIR / "budget_test_summary.md"
    summary_md.write_text(
        "\n".join(
            [
                "# Budget-Constrained Meal Planner Test Summary",
                "",
                f"- Executed cases: {len(rows)}",
                f"- Passed cases: {pass_count}",
                f"- Failed cases: {len(rows) - pass_count}",
                f"- % within budget for feasible set (cases 5,6,8,10,11,12,13,14): {feasible_pct:.2f}% ({feasible_within}/{len(feasible_rows)})",
                f"- % over-budget with warnings for strict set (cases 15,16): {strict_pct:.2f}% ({strict_overwarn}/{len(strict_rows)})",
                f"- Average overrun for failed budget-on cases: EUR {avg_overrun:.2f}",
                "",
                "## Known Limitations",
                "- Costs are rough estimates based on ingredient pricing heuristics.",
                "- Prompt mode does not currently parse a budget cap directly; budget is tested via manual mode.",
                "",
                "## Evidence Files",
                "- `budget_test_results.csv`",
                "- `evidence_within_budget.json`",
                "- `evidence_over_budget.json`",
            ]
        ),
        encoding="utf-8",
    )

    ui_md = REPORT_DIR / "ui_screenshot_checklist.md"
    ui_md.write_text(
        "\n".join(
            [
                "# UI Screenshot Checklist (Manual Capture)",
                "",
                "Capture these 4 screenshots from the web UI and store in this folder:",
                "",
                "1. Within-budget success: use case similar to #5 (manual, cap=40).",
                "2. Over-budget warning: use strict case similar to #15 or #16.",
                "3. No-budget baseline: case #17 or #18 (budget toggle off).",
                "4. Constrained dietary + budget: case #11 or #12.",
                "",
                "Recommended filename format:",
                "- `ui_case_within_budget.png`",
                "- `ui_case_over_budget.png`",
                "- `ui_case_no_budget.png`",
                "- `ui_case_dietary_budget.png`",
            ]
        ),
        encoding="utf-8",
    )

    print(json.dumps({
        "report_dir": str(REPORT_DIR),
        "cases": len(rows),
        "passed": pass_count,
        "failed": len(rows) - pass_count,
        "feasible_within_pct": round(feasible_pct, 2),
        "strict_warning_pct": round(strict_pct, 2),
        "avg_failed_overrun_eur": round(avg_overrun, 2),
    }, indent=2))


if __name__ == "__main__":
    main()

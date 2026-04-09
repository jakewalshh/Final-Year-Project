import json
import os
import re
from dataclasses import dataclass
from statistics import median

from django.core.management.base import BaseCommand, CommandError

from recipes.models import Ingredient


@dataclass
class IngredientRow:
    id: int
    name: str
    canonical: str


def _chunked(values, size):
    for i in range(0, len(values), size):
        yield values[i : i + size]


class Command(BaseCommand):
    help = "Estimate EUR cost per ingredient and store it in Ingredient.estimated_unit_cost_eur."

    def add_arguments(self, parser):
        parser.add_argument("--model", default=os.environ.get("INGREDIENT_COST_MODEL", "gpt-4o-mini"))
        parser.add_argument("--batch-size", type=int, default=120)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--force", action="store_true", help="Re-estimate costs for all ingredients.")
        parser.add_argument("--dry-run", action="store_true", help="Do not write values to DB.")
        parser.add_argument(
            "--rules-only",
            action="store_true",
            help="Populate prices deterministically from existing DB prices (no OpenAI calls).",
        )

    def _estimate_batch(self, client, model: str, canonical_terms: list[str]) -> dict[str, float]:
        completion = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You estimate rough supermarket prices in EUR for ingredient labels. "
                        "Return strict JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Estimate a realistic rough EUR unit cost for each canonical ingredient term. "
                        "Use consistent practical grocery assumptions and avoid random values. "
                        "Return this exact JSON schema only:\n"
                        "{\n"
                        '  "prices": [\n'
                        "    {\n"
                        '      "ingredient": "<exact canonical term from input>",\n'
                        '      "estimated_unit_cost_eur": <number>\n'
                        "    }\n"
                        "  ]\n"
                        "}\n\n"
                        f"Canonical terms: {json.dumps(canonical_terms)}"
                    ),
                },
            ],
        )
        payload = json.loads(completion.choices[0].message.content)
        rows = payload.get("prices")
        if not isinstance(rows, list):
            return {}

        out = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("ingredient") or "").strip().lower()
            if not name:
                continue
            try:
                cost = float(row.get("estimated_unit_cost_eur"))
            except (TypeError, ValueError):
                continue
            if cost <= 0 or cost > 100:
                continue
            out[name] = round(cost, 2)
        return out

    @staticmethod
    def _canonical_ingredient_name(raw_name: str) -> str:
        patterns = [
            (r"\bchichken\b", "chicken"),
            (r"\bchicken\b", "chicken"),
            (r"\bturkey\b", "turkey"),
            (r"\bbeef\b|\bsteak\b", "beef"),
            (r"\bpork\b|\bham\b|\bbacon\b", "pork"),
            (r"\bsalmon\b|\btuna\b|\bcod\b|\bhalibut\b|\bfish\b", "fish"),
            (r"\bshrimp\b|\bprawn\b", "shrimp"),
            (r"\bgarlic\b", "garlic"),
            (r"\bonion\b|\bshallot\b|\bscallion\b", "onion"),
            (r"\bpotato\b", "potato"),
            (r"\btomato\b", "tomato"),
        ]
        stopwords = {
            "fresh",
            "chopped",
            "diced",
            "sliced",
            "large",
            "small",
            "extra",
            "virgin",
            "boneless",
            "skinless",
            "lean",
            "ground",
            "minced",
            "breast",
            "breasts",
            "thigh",
            "thighs",
            "fillet",
            "fillets",
            "halves",
        }
        cleaned = str(raw_name or "").strip().lower()
        if not cleaned:
            return ""
        cleaned = cleaned.replace("&", " and ")
        cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        for pattern, replacement in patterns:
            if re.search(pattern, cleaned):
                return replacement
        tokens = [token for token in cleaned.split() if token and token not in stopwords]
        if not tokens:
            tokens = cleaned.split()
        if not tokens:
            return ""
        token = tokens[0]
        if token.endswith("es") and len(token) > 4:
            token = token[:-2]
        elif token.endswith("s") and len(token) > 3:
            token = token[:-1]
        return token

    @staticmethod
    def _tokenize(name: str) -> list[str]:
        stop = {
            "fresh",
            "chopped",
            "diced",
            "sliced",
            "large",
            "small",
            "extra",
            "virgin",
            "boneless",
            "skinless",
            "lean",
            "ground",
            "minced",
            "breast",
            "breasts",
            "thigh",
            "thighs",
            "fillet",
            "fillets",
            "halves",
            "of",
            "and",
            "with",
            "in",
        }
        cleaned = re.sub(r"[^a-z0-9\s]", " ", str(name or "").strip().lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return []
        return [t for t in cleaned.split(" ") if t and t not in stop and len(t) > 2]

    def handle(self, *args, **options):
        model = str(options["model"]).strip()
        batch_size = max(10, int(options["batch_size"]))
        limit = int(options["limit"])
        force = bool(options["force"])
        dry_run = bool(options["dry_run"])
        rules_only = bool(options["rules_only"])

        api_key = os.environ.get("OPENAI_API_KEY")
        client = None
        if not rules_only:
            if not api_key:
                raise CommandError("OPENAI_API_KEY is required unless --rules-only is used.")
            try:
                from openai import OpenAI
            except Exception as exc:
                raise CommandError(f"OpenAI client import failed: {exc}") from exc
            client = OpenAI(api_key=api_key)

        qs = Ingredient.objects.all().order_by("id")
        if not force:
            qs = qs.filter(estimated_unit_cost_eur__isnull=True)
        if limit > 0:
            qs = qs[:limit]

        rows = [
            IngredientRow(
                id=row.id,
                name=row.name.strip(),
                canonical=self._canonical_ingredient_name(row.name),
            )
            for row in qs
        ]
        if not rows:
            self.stdout.write(self.style.SUCCESS("No ingredient rows require updates."))
            return
        updated = 0
        missing = 0
        errors = 0

        existing_canonical_buckets: dict[str, list[float]] = {}
        token_cost_buckets: dict[str, list[float]] = {}
        all_known_costs: list[float] = []
        existing_rows = Ingredient.objects.exclude(estimated_unit_cost_eur__isnull=True).values_list("name", "estimated_unit_cost_eur")
        for name, cost in existing_rows:
            cost_value = float(cost)
            all_known_costs.append(cost_value)
            canonical = self._canonical_ingredient_name(name)
            if not canonical:
                continue
            existing_canonical_buckets.setdefault(canonical, []).append(cost_value)
            for tok in self._tokenize(name):
                token_cost_buckets.setdefault(tok, []).append(cost_value)

        existing_canonical_prices = {
            key: round(sum(values) / len(values), 2)
            for key, values in existing_canonical_buckets.items()
            if values
        }
        token_avg_prices = {
            key: round(sum(values) / len(values), 2)
            for key, values in token_cost_buckets.items()
            if len(values) >= 3
        }
        global_default = round(float(median(all_known_costs)), 2) if all_known_costs else 0.75

        unresolved_rows = [row for row in rows if row.canonical and row.canonical not in existing_canonical_prices]
        canonical_terms = sorted({row.canonical for row in unresolved_rows})
        canonical_prices: dict[str, float] = {}

        if rules_only:
            self.stdout.write(
                f"Rule-only population for {len(rows)} ingredients "
                f"(existing canonical prices={len(existing_canonical_prices)}, token prices={len(token_avg_prices)}, default={global_default}, dry_run={dry_run})"
            )
        else:
            self.stdout.write(
                f"Estimating costs for {len(rows)} ingredients via {len(canonical_terms)} unresolved canonical terms "
                f"(batch_size={batch_size}, model={model}, dry_run={dry_run})"
            )
            for batch in _chunked(canonical_terms, batch_size):
                try:
                    estimated = self._estimate_batch(client, model, batch)
                except Exception as exc:
                    errors += len(batch)
                    self.stdout.write(self.style.WARNING(f"Canonical batch failed ({len(batch)} rows): {exc}"))
                    continue
                canonical_prices.update(estimated)

        to_update = []
        for row in rows:
            cost = canonical_prices.get(row.canonical)
            if cost is None:
                cost = existing_canonical_prices.get(row.canonical)
            if cost is None:
                token_candidates = [token_avg_prices[t] for t in self._tokenize(row.name) if t in token_avg_prices]
                if token_candidates:
                    cost = round(sum(token_candidates) / len(token_candidates), 2)
            if cost is None:
                cost = global_default
            if cost is None:
                missing += 1
                continue
            to_update.append(Ingredient(id=row.id, estimated_unit_cost_eur=cost))

        updated = len(to_update)
        if to_update and not dry_run:
            Ingredient.objects.bulk_update(to_update, ["estimated_unit_cost_eur"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. updated={updated} missing={missing} batch_errors={errors} dry_run={dry_run}"
            )
        )

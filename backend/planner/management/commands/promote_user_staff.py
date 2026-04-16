from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Promote a user to staff role (idempotent)."

    def add_arguments(self, parser):
        # Allow staff promotion target to be passed from CLI.
        parser.add_argument(
            "--email",
            default="jake@jake.com",
            help="Email of user to promote. Defaults to jake@jake.com",
        )

    def handle(self, *args, **options):
        # Promote one user to staff in an idempotent way.
        email = str(options.get("email") or "").strip().lower()
        if not email:
            self.stderr.write(self.style.ERROR("Email is required."))
            return

        user_model = get_user_model()
        user = user_model.objects.filter(email=email).first()
        if user is None:
            self.stderr.write(self.style.ERROR(f"User not found: {email}"))
            return

        changed = False
        if not user.is_staff:
            user.is_staff = True
            changed = True

        # Keep superuser unchanged unless explicitly managed elsewhere.
        if changed:
            user.save(update_fields=["is_staff"])
            self.stdout.write(self.style.SUCCESS(f"Promoted to staff: {email}"))
            return

        self.stdout.write(self.style.WARNING(f"Already staff: {email}"))

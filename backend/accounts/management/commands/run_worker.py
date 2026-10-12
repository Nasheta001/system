import time

from django.core.management.base import BaseCommand

from config.jobs import run_all_jobs


class Command(BaseCommand):
    help = "Run scheduled jobs (rent charges, reminders, reservation expiry, scheduled notices, retries)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run once and exit")
        parser.add_argument("--interval", type=int, default=300, help="Seconds between runs (default 300)")

    def handle(self, *args, **opts):
        while True:
            results = run_all_jobs()
            self.stdout.write(self.style.SUCCESS(f"Jobs: {results}"))
            if opts["once"]:
                break
            time.sleep(max(30, opts["interval"]))

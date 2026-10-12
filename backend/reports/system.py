from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import audit
from accounts.permissions import StaffCapability
from config.jobs import run_all_jobs


class RunJobsView(APIView):
    """Lets an administrator run the scheduled jobs immediately (useful for demos
    and when the worker is not running)."""

    permission_classes = [StaffCapability]
    read_cap = "manage_settings"
    write_cap = "manage_settings"

    def post(self, request):
        results = run_all_jobs()
        audit(request, "system.run_jobs", None, "Ran scheduled jobs manually", changes=results)
        return Response(results)

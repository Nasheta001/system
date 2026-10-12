from .models import AuditLog


def client_ip(request):
    """Real client IP. Only the right-most NUM_PROXIES entries of
    X-Forwarded-For are trusted (added by CloudFront and the ALB); anything
    further left can be forged by the client, so it is ignored."""
    if request is None:
        return None
    from django.conf import settings

    num_proxies = getattr(settings, "NUM_PROXIES", 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if num_proxies and forwarded:
        addrs = [a.strip() for a in forwarded.split(",") if a.strip()]
        if addrs:
            return addrs[-min(num_proxies, len(addrs))]
    return request.META.get("REMOTE_ADDR")


def audit(request, action, obj=None, summary="", changes=None, property_id=None, actor=None):
    """Record an important administrative action."""
    user = actor or (request.user if request is not None and request.user.is_authenticated else None)
    if property_id is None and obj is not None:
        property_id = getattr(obj, "property_id", None)
        if property_id is None and obj.__class__.__name__ == "Property":
            property_id = obj.pk
    return AuditLog.objects.create(
        actor=user,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None and obj.pk is not None else "",
        summary=(summary or str(obj))[:500],
        changes=changes or {},
        property_id=property_id,
        ip_address=client_ip(request),
    )

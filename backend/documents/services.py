from django.db import transaction
from django.db.models import Q

from accounts.permissions import accessible_property_ids
from tenancies.models import Tenancy, Tenant

from .models import Document, DocumentAcknowledgement, DocumentAssignment, SignatureRequest


def visible_documents_for_tenant(tenant):
    """Approved documents a tenant may open. Property/building/portfolio-wide
    documents require a *current* tenancy; personal documents remain available
    to former tenants."""
    current = tenant.tenancies.filter(status__in=Tenancy.CURRENT_STATUSES)
    q = Q(tenant=tenant) | Q(tenancy__tenant=tenant) | Q(assignments__scope="tenant", assignments__tenant=tenant)
    if current.exists():
        prop_ids = list(current.values_list("property_id", flat=True))
        building_ids = [b for b in current.values_list("unit__building_id", flat=True) if b]
        q |= (Q(assignments__scope="all_tenants")
              | Q(assignments__scope="property", assignments__property_id__in=prop_ids)
              | Q(assignments__scope="building", assignments__building_id__in=building_ids))
    return Document.objects.filter(q, status=Document.Status.APPROVED, current_version__isnull=False).distinct()


def eligible_tenants(document):
    """Tenants who can currently see the document."""
    tenancies = Tenancy.objects.filter(status__in=Tenancy.CURRENT_STATUSES)
    q = Q(pk__in=[])
    for a in document.assignments.all():
        if a.scope == "all_tenants":
            q |= Q(pk__in=tenancies.values("tenant_id"))
        elif a.scope == "property":
            q |= Q(pk__in=tenancies.filter(property_id=a.property_id).values("tenant_id"))
        elif a.scope == "building":
            q |= Q(pk__in=tenancies.filter(unit__building_id=a.building_id).values("tenant_id"))
        elif a.scope == "tenant":
            q |= Q(pk=a.tenant_id)
    if document.tenant_id:
        q |= Q(pk=document.tenant_id)
    if document.tenancy_id:
        q |= Q(pk=document.tenancy.tenant_id)
    return Tenant.objects.filter(q).distinct()


def scoped_documents(user):
    ids = accessible_property_ids(user)
    qs = Document.objects.all()
    if ids is None:
        return qs
    return qs.filter(
        Q(property_id__in=ids)
        | Q(property__isnull=True, tenant__isnull=True, tenancy__isnull=True)  # company-wide library (read)
        | Q(tenant__tenancies__property_id__in=ids)
        | Q(tenancy__property_id__in=ids)
    ).distinct()


def can_edit_document(user, document):
    ids = accessible_property_ids(user)
    if ids is None:
        return True
    if document.property_id:
        return document.property_id in ids
    if document.tenancy_id:
        return document.tenancy.property_id in ids
    if document.tenant_id:
        return document.tenant.tenancies.filter(property_id__in=ids).exists()
    return False  # company-wide documents are managed by portfolio administrators


def notify_document_action(document, tenants):
    from communications.services import notify_tenant

    if document.workflow == Document.Workflow.INFO or document.status != Document.Status.APPROVED:
        return
    action = "signature" if document.workflow == Document.Workflow.SIGNATURE else "acknowledgement"
    for t in tenants:
        transaction.on_commit(lambda t=t: notify_tenant(
            t, "document_action", {"title": document.title, "action": action}, link="/tenant/documents",
            dedupe=f"doc:{document.current_version_id}:t{t.pk}", related=("Document", document.pk),
        ))


def create_signature_requests(document, tenants, user, due_date=None):
    created = []
    for t in tenants:
        exists = SignatureRequest.objects.filter(
            version=document.current_version, tenant=t, status__in=["pending", "submitted", "verified"]
        ).exists()
        if not exists:
            created.append(SignatureRequest.objects.create(
                document=document, version=document.current_version, tenant=t, created_by=user, due_date=due_date))
    return created


def tenant_pending_document_actions(tenant):
    out = []
    docs = visible_documents_for_tenant(tenant).filter(workflow=Document.Workflow.ACKNOWLEDGE)
    acked = set(DocumentAcknowledgement.objects.filter(tenant=tenant).values_list("version_id", flat=True))
    for d in docs:
        if d.current_version_id not in acked:
            out.append({"document_id": d.pk, "title": d.title, "action": "acknowledge"})
    for s in SignatureRequest.objects.filter(tenant=tenant, status__in=["pending", "rejected"]).select_related("document"):
        out.append({"document_id": s.document_id, "title": s.document.title, "action": "sign",
                    "signature_request_id": s.pk, "status": s.status})
    return out

"""M-Pesa Daraja STK Push integration.

Modes (settings.MPESA["MODE"]):
  disabled   – online payment is switched off.
  simulated  – no request leaves the server. The tenant portal shows a clearly
               labelled "simulate phone response" step. Resulting payments are
               flagged is_simulated=True and method=mpesa_simulated, and are
               never presented as real M-Pesa transactions.
  sandbox    – Safaricom Daraja sandbox (https://sandbox.safaricom.co.ke).
  production – Live Daraja API.

Security model for callbacks:
  * The callback URL contains a long secret token (MPESA_CALLBACK_TOKEN),
    compared in constant time.
  * Optional IP allow-list (MPESA_ALLOWED_CALLBACK_IPS).
  * The callback must reference a CheckoutRequestID we created.
  * In sandbox/production, a successful callback is confirmed with the STK
    Query API before money is credited; amount must match the request.
  * Processing is idempotent: row lock on the transaction, final states are
    never re-processed and Payment.mpesa_receipt is unique.
"""
import base64
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import MpesaTransaction, Payment
from .services import assign_receipt_number, notify_payment_received

logger = logging.getLogger(__name__)

BASE_URLS = {"sandbox": "https://sandbox.safaricom.co.ke", "production": "https://api.safaricom.co.ke"}
RESULT_CANCELLED = {"1032"}
RESULT_TIMEOUT = {"1037"}


class MpesaError(Exception):
    pass


def mode():
    return settings.MPESA["MODE"]


def normalize_phone(phone):
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif digits.startswith("7") or digits.startswith("1"):
        if len(digits) == 9:
            digits = "254" + digits
    if not re.fullmatch(r"254[17]\d{8}", digits):
        raise MpesaError("Enter a valid Safaricom number, e.g. 0712345678.")
    return digits


def _cfg():
    return settings.MPESA


def _access_token():
    cfg = _cfg()
    if not (cfg["CONSUMER_KEY"] and cfg["CONSUMER_SECRET"]):
        raise MpesaError("M-Pesa credentials are not configured.")
    url = f"{BASE_URLS[mode()]}/oauth/v1/generate?grant_type=client_credentials"
    try:
        resp = requests.get(url, auth=(cfg["CONSUMER_KEY"], cfg["CONSUMER_SECRET"]), timeout=20)
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("M-Pesa token error: %s", exc)
        raise MpesaError("Could not connect to M-Pesa. Please try again shortly.") from exc


def _password(timestamp):
    cfg = _cfg()
    raw = f"{cfg['SHORTCODE']}{cfg['PASSKEY']}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


def callback_url():
    cfg = _cfg()
    return f"{cfg['CALLBACK_BASE_URL']}/api/payments/mpesa/callback/{cfg['CALLBACK_TOKEN']}/"


def initiate_stk_push(tenancy, phone, amount, user):
    current_mode = mode()
    if current_mode == "disabled":
        raise MpesaError("Online M-Pesa payments are not enabled. Please pay at the office or contact management.")
    try:
        amount = Decimal(amount).quantize(Decimal("1"))
    except (InvalidOperation, TypeError) as exc:
        raise MpesaError("Enter a valid amount.") from exc
    if amount < 1 or amount > 250000:
        raise MpesaError("Amount must be between KES 1 and KES 250,000 (M-Pesa transaction limit).")
    phone = normalize_phone(phone)
    account_ref = re.sub(r"[^A-Za-z0-9]", "", f"{tenancy.unit.unit_number}{tenancy.property_id}")[:12] or "RENT"

    if current_mode == "simulated":
        return MpesaTransaction.objects.create(
            tenancy=tenancy, initiated_by=user, phone=phone, amount=amount, account_reference=account_ref,
            merchant_request_id=f"SIM-{secrets.token_hex(6)}", checkout_request_id=f"SIM-{secrets.token_hex(12)}",
            is_simulated=True,
        )

    if not _cfg()["CALLBACK_BASE_URL"].startswith("https://"):
        raise MpesaError("M-Pesa callback URL is not configured (HTTPS required).")
    token = _access_token()
    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    payload = {
        "BusinessShortCode": _cfg()["SHORTCODE"],
        "Password": _password(timestamp),
        "Timestamp": timestamp,
        "TransactionType": _cfg()["TRANSACTION_TYPE"],
        "Amount": int(amount),
        "PartyA": phone,
        "PartyB": _cfg()["SHORTCODE"],
        "PhoneNumber": phone,
        "CallBackURL": callback_url(),
        "AccountReference": account_ref,
        "TransactionDesc": "Rent payment",
    }
    try:
        resp = requests.post(
            f"{BASE_URLS[current_mode]}/mpesa/stkpush/v1/processrequest", json=payload, timeout=30,
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("STK push request failed: %s", exc)
        raise MpesaError("Could not reach M-Pesa. Please try again.") from exc
    if str(data.get("ResponseCode")) != "0":
        logger.warning("STK push rejected: %s", data)
        raise MpesaError(data.get("errorMessage") or data.get("ResponseDescription") or "M-Pesa rejected the request.")
    return MpesaTransaction.objects.create(
        tenancy=tenancy, initiated_by=user, phone=phone, amount=amount, account_reference=account_ref,
        merchant_request_id=data.get("MerchantRequestID", ""), checkout_request_id=data["CheckoutRequestID"],
    )


def query_stk_status(txn):
    """Ask Daraja for the final result of an STK push. Returns (result_code, desc)
    or (None, reason) if the result is not yet available."""
    if txn.is_simulated or mode() not in BASE_URLS:
        return None, "not applicable"
    token = _access_token()
    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    payload = {
        "BusinessShortCode": _cfg()["SHORTCODE"],
        "Password": _password(timestamp),
        "Timestamp": timestamp,
        "CheckoutRequestID": txn.checkout_request_id,
    }
    try:
        resp = requests.post(f"{BASE_URLS[mode()]}/mpesa/stkpushquery/v1/query", json=payload, timeout=30,
                             headers={"Authorization": f"Bearer {token}"})
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    if "ResultCode" not in data:
        return None, data.get("errorMessage", "pending")
    return str(data["ResultCode"]), data.get("ResultDesc", "")


def verify_callback_request(request, token):
    cfg = _cfg()
    if not hmac.compare_digest(str(token), str(cfg["CALLBACK_TOKEN"])):
        return False
    allowed = cfg["ALLOWED_CALLBACK_IPS"]
    if allowed:
        from accounts.audit import client_ip

        return client_ip(request) in allowed
    return True


def _metadata(callback):
    items = callback.get("CallbackMetadata", {}).get("Item", [])
    return {i.get("Name"): i.get("Value") for i in items if isinstance(i, dict)}


def process_stk_callback(payload, simulated=False, confirm_with_query=None):
    """Apply an STK callback. Returns the transaction (or None if unknown)."""
    try:
        cb = payload["Body"]["stkCallback"]
        checkout_id = str(cb["CheckoutRequestID"])
        result_code = str(cb["ResultCode"])
    except (KeyError, TypeError):
        logger.warning("Malformed M-Pesa callback ignored")
        return None
    if confirm_with_query is None:
        confirm_with_query = mode() in BASE_URLS and not simulated

    with transaction.atomic():
        txn = MpesaTransaction.objects.select_for_update().filter(checkout_request_id=checkout_id).first()
        if txn is None:
            logger.warning("Callback for unknown CheckoutRequestID %s", checkout_id)
            return None
        txn.callback_count += 1
        late_success = txn.status == MpesaTransaction.Status.TIMEOUT and result_code == "0"
        if txn.status in MpesaTransaction.FINAL_STATUSES and not late_success:
            # Duplicate / late callback: record that it arrived, change nothing.
            # (A success arriving after our own timeout is still applied, because
            # the customer's money has actually moved.)
            txn.save(update_fields=["callback_count"])
            return txn
        if txn.is_simulated != simulated:
            logger.warning("Callback mode mismatch for %s – ignored", checkout_id)
            txn.save(update_fields=["callback_count"])
            return txn
        txn.raw_callback = payload
        txn.result_code = result_code
        txn.result_desc = str(cb.get("ResultDesc", ""))[:255]

        if result_code != "0":
            txn.status = (
                MpesaTransaction.Status.CANCELLED if result_code in RESULT_CANCELLED
                else MpesaTransaction.Status.TIMEOUT if result_code in RESULT_TIMEOUT
                else MpesaTransaction.Status.FAILED
            )
            txn.completed_at = timezone.now()
            txn.save()
            return txn

        meta = _metadata(cb)
        receipt = str(meta.get("MpesaReceiptNumber") or "").strip()
        try:
            paid_amount = Decimal(str(meta.get("Amount")))
        except (InvalidOperation, TypeError):
            paid_amount = None
        if not receipt or paid_amount is None:
            txn.status = MpesaTransaction.Status.FAILED
            txn.result_desc = "Success callback missing receipt or amount – flagged for review"
            txn.completed_at = timezone.now()
            txn.save()
            return txn

        if confirm_with_query:
            code, _desc = query_stk_status(txn)
            if code is None:
                # Cannot confirm yet: keep pending, the worker will re-query.
                txn.mpesa_receipt = receipt
                txn.save()
                return txn
            if code != "0":
                txn.status = MpesaTransaction.Status.FAILED
                txn.result_desc = "Callback not confirmed by STK query"
                txn.completed_at = timezone.now()
                txn.save()
                return txn

        _record_success(txn, receipt, paid_amount)
    return txn


def _record_success(txn, receipt, paid_amount):
    """Create the verified payment for a successful transaction (inside an
    atomic block holding the transaction row lock)."""
    txn.mpesa_receipt = receipt
    txn.status = MpesaTransaction.Status.SUCCESS
    txn.completed_at = timezone.now()
    existing = Payment.objects.filter(mpesa_receipt=receipt).first()
    if existing:
        linked = MpesaTransaction.objects.filter(payment=existing).exclude(pk=txn.pk).exists()
        if linked:
            # The receipt was already applied via another request: never count it twice.
            txn.status = MpesaTransaction.Status.FAILED
            txn.result_desc = f"Receipt {receipt} already applied to another transaction – flagged for review"
        else:
            txn.payment = existing
        txn.save()
        return existing
    amount_matches = paid_amount == txn.amount
    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                tenancy=txn.tenancy,
                property_id=txn.tenancy.property_id,
                amount=paid_amount,
                method=Payment.Method.MPESA_SIMULATED if txn.is_simulated else Payment.Method.MPESA,
                source=Payment.Source.STK,
                reference=receipt,
                mpesa_receipt=receipt,
                paid_on=timezone.localdate(),
                is_simulated=txn.is_simulated,
                status=Payment.Status.VERIFIED if amount_matches else Payment.Status.PENDING,
                verified_at=timezone.now() if amount_matches else None,
                notes="" if amount_matches else f"Amount mismatch: requested {txn.amount}, received {paid_amount}",
                recorded_by=txn.initiated_by,
            )
            if amount_matches:
                assign_receipt_number(payment)
                payment.save(update_fields=["receipt_number"])
    except IntegrityError:
        payment = Payment.objects.get(mpesa_receipt=receipt)
    txn.payment = payment
    txn.save()
    if payment.status == Payment.Status.VERIFIED:
        transaction.on_commit(lambda: notify_payment_received(payment.pk))
    return payment


def simulate_callback(txn, outcome):
    """Build a Daraja-shaped callback for SIMULATED mode only."""
    if mode() != "simulated" or not txn.is_simulated:
        raise MpesaError("Simulation is only available in simulated mode.")
    if outcome == "success":
        payload = {"Body": {"stkCallback": {
            "MerchantRequestID": txn.merchant_request_id, "CheckoutRequestID": txn.checkout_request_id,
            "ResultCode": 0, "ResultDesc": "SIMULATED: The service request is processed successfully.",
            "CallbackMetadata": {"Item": [
                {"Name": "Amount", "Value": float(txn.amount)},
                {"Name": "MpesaReceiptNumber", "Value": f"SIM{secrets.token_hex(4).upper()}"},
                {"Name": "TransactionDate", "Value": int(datetime.now().strftime("%Y%m%d%H%M%S"))},
                {"Name": "PhoneNumber", "Value": int(txn.phone)},
            ]},
        }}}
    else:
        payload = {"Body": {"stkCallback": {
            "MerchantRequestID": txn.merchant_request_id, "CheckoutRequestID": txn.checkout_request_id,
            "ResultCode": 1032, "ResultDesc": "SIMULATED: Request cancelled by user",
        }}}
    return process_stk_callback(payload, simulated=True)


def reconcile_pending(now=None):
    """Resolve STK transactions whose callback is late or missing."""
    now = now or timezone.now()
    timeout = timedelta(minutes=_cfg()["TIMEOUT_MINUTES"])
    resolved = 0
    for txn in MpesaTransaction.objects.filter(status=MpesaTransaction.Status.PENDING,
                                               created_at__lte=now - timedelta(minutes=1)):
        if not txn.is_simulated and mode() in BASE_URLS:
            code, desc = query_stk_status(txn)
            if code is not None:
                with transaction.atomic():
                    locked = MpesaTransaction.objects.select_for_update().get(pk=txn.pk)
                    if locked.status != MpesaTransaction.Status.PENDING:
                        continue
                    locked.last_queried_at = now
                    if code == "0" and locked.raw_callback:
                        meta = _metadata(locked.raw_callback.get("Body", {}).get("stkCallback", {}))
                        _record_success(locked, str(meta.get("MpesaReceiptNumber")), Decimal(str(meta.get("Amount"))))
                    elif code != "0":
                        locked.status = (MpesaTransaction.Status.CANCELLED if code in RESULT_CANCELLED
                                         else MpesaTransaction.Status.FAILED)
                        locked.result_code, locked.result_desc = code, desc[:255]
                        locked.completed_at = now
                        locked.save()
                    else:
                        # Confirmed success but receipt not yet received – wait for callback
                        locked.save(update_fields=["last_queried_at"])
                        continue
                resolved += 1
                continue
        if txn.created_at <= now - timeout:
            MpesaTransaction.objects.filter(pk=txn.pk, status=MpesaTransaction.Status.PENDING).update(
                status=MpesaTransaction.Status.TIMEOUT, completed_at=now,
                result_desc="No confirmation received before timeout",
            )
            resolved += 1
    return resolved

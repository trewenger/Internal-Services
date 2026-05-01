from common.Clients.Fishbowl.FishbowlSession import FishbowlSession


def _build_payload(name, description, discount_type, discount_amount, active):
    headers = ['Name', 'Description', 'Type', 'Amount', 'Percentage', 'Taxable', 'Active']
    if discount_type == 'percentage':
        fb_type, fb_amount, fb_pct = 'Percentage', 0.00, float(discount_amount)
    else:
        fb_type, fb_amount, fb_pct = 'Amount', float(discount_amount), 0
    row = [name, description, fb_type, fb_amount, fb_pct, True, active]
    return [headers, row]


def upsert_discount(name, description, discount_type, discount_amount, active):
    """
    Create or update a Fishbowl discount. Returns True on success, False on failure.
    Never raises — callers check the return value.
    """
    payload = _build_payload(name, description, discount_type, discount_amount, active)
    session = FishbowlSession(is_test_db=False, login_attempts=1, attempt_wait_secs=0)
    try:
        session.update_discounts(payload)
        return True
    except Exception:
        return False
    finally:
        try:
            session.logout()
        except Exception:
            pass


def get_discounts():
    """Fetch all Fishbowl discounts. Returns data list or None on failure."""
    session = FishbowlSession(is_test_db=False, login_attempts=1, attempt_wait_secs=0)
    try:
        result = session.get_discounts()
        return result.get('data')
    except Exception:
        return None
    finally:
        try:
            session.logout()
        except Exception:
            pass

from services.free_promos import send_test_promo


if __name__ == "__main__":
    ok = send_test_promo()
    raise SystemExit(0 if ok else 1)

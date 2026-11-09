import pytest
from voizy_core.domain.integrations import BY_ID, INTEGRATIONS, RESERVED_SECRET_NAMES


def test_every_integration_field_is_reserved_and_names_are_unique() -> None:
    names = [f.name for i in INTEGRATIONS for f in i.fields]
    assert len(names) == len(set(names)) and set(names) == RESERVED_SECRET_NAMES
    assert set(BY_ID) == {"livekit", "twilio", "openai", "google", "deepgram", "cartesia"}


@pytest.mark.parametrize(
    ("field", "good", "bad"),
    [
        ("livekit_url", "wss://proj-abc.livekit.cloud", "https://proj.livekit.cloud"),
        ("livekit_url", "wss://livekit.example.com:7880", "wss://x/path"),
        ("livekit_api_key", "APIabc123def", "short"),
        ("twilio_account_sid", "AC" + "a" * 32, "AC123"),
        ("twilio_auth_token", "b" * 32, "z" * 32),
        ("openai_api_key", "sk-" + "a" * 40, "sk-" + "a b" * 10),
        # Provider key formats change; any one-line printable key of sensible length is accepted.
        ("google_api_key", "AIza" + "x" * 35, "AIza short"),
        # A newer Google key shape: an "AQ." prefix with a dot, then mixed characters.
        ("google_api_key", "AQ.Ab" + "x1_Y" * 12, "x" * 10),
        ("deepgram_api_key", "a1B2-c3.D4_e5" * 3, "has a space " * 3),
        ("cartesia_api_key", "sk_car_" + "x" * 30, "tab\there" * 4),
    ],
)
def test_field_patterns(field: str, good: str, bad: str) -> None:
    f = next(f for i in INTEGRATIONS for f in i.fields if f.name == field)
    assert f.valid(good) and not f.valid(bad)


def test_values_with_line_breaks_are_never_valid() -> None:
    f = next(f for i in INTEGRATIONS for f in i.fields if f.name == "livekit_api_key")
    assert not f.valid("APIabc123def\nX-Injected: 1")


def test_only_non_sensitive_fields_are_shown_back() -> None:
    shown = {f.name for i in INTEGRATIONS for f in i.fields if not f.secret}
    assert shown == {"livekit_url", "twilio_account_sid"}

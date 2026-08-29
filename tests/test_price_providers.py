import json

from stockscanner.price_providers import (
    download_alpaca_snapshots,
    download_twelve_data_snapshots,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_alpaca_uses_iex_batch_and_maps_share_class_symbols():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "AAA": {
                    "latestTrade": {"p": 10.25, "t": "2026-08-28T14:00:00Z"},
                    "prevDailyBar": {"c": 10.0},
                },
                "BRK.B": {"minuteBar": {"c": 500.5, "t": "2026-08-28T14:00:00Z"}},
            }
        )

    results = download_alpaca_snapshots(
        ["AAA", "BRK-B"],
        api_key_id="test-id",
        api_secret_key="test-secret",
        opener=opener,
    )

    request = captured["request"]
    assert "feed=iex" in request.full_url
    assert "AAA%2CBRK.B" in request.full_url
    assert request.get_header("Apca-api-key-id") == "test-id"
    assert request.get_header("Apca-api-secret-key") == "test-secret"
    assert results["AAA"]["price"] == 10.25
    assert results["AAA"]["daily_close"] == 10.0
    assert results["BRK-B"]["price"] == 500.5


def test_twelve_data_never_requests_more_than_eight_symbols():
    captured = {}
    symbols = [f"S{index}" for index in range(12)]

    def opener(request, timeout):
        captured["request"] = request
        requested = symbols[:8]
        return FakeResponse({symbol: {"price": "11.5"} for symbol in requested})

    results = download_twelve_data_snapshots(
        symbols,
        api_key="test-key",
        opener=opener,
    )

    assert "%2CS7" in captured["request"].full_url
    assert "S8" not in captured["request"].full_url
    assert len(results) == 8

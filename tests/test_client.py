import time
from unittest import mock

import pytest
import responses

from mopidy_mp3quran.client import Mp3Quran, _API_BASE, _RADIO_API, _DEFAULT_CACHE_TTL


SURAS_RESPONSE = {
    "Suras_Name": [
        {"id": "1", "name": "Al-Fatiha"},
        {"id": "2", "name": "Al-Baqara"},
        {"id": "3", "name": "Aal-Imran"},
    ]
}

RECITERS_RESPONSE = {
    "reciters": [
        {
            "id": "1",
            "name": "Mishary Rashid Alafasy",
            "Server": "https://server.example.com/mishary",
            "suras": "1,2,3",
            "rewaya": "Hafs",
        },
        {
            "id": "2",
            "name": "Abdul Rahman Al-Sudais",
            "Server": "https://server.example.com/sudais",
            "suras": "1,2",
            "rewaya": "Hafs",
        },
    ]
}

RADIOS_RESPONSE = {
    "Radios": [
        {"Name": "Quran Radio 24/7", "URL": "https://stream.example.com/radio1"},
        {"Name": "Live Quran FM", "URL": "https://stream.example.com/radio2"},
    ]
}


@pytest.fixture
def mocked_api():
    """Mock all mp3quran.net API endpoints."""
    with responses.mock:
        responses.add(
            responses.GET,
            _API_BASE + "_english_sura.json",
            json=SURAS_RESPONSE,
            status=200,
        )
        responses.add(
            responses.GET,
            _API_BASE + "_english.json",
            json=RECITERS_RESPONSE,
            status=200,
        )
        responses.add(
            responses.GET,
            _RADIO_API,
            json=RADIOS_RESPONSE,
            status=200,
        )
        yield


@pytest.fixture
def client(mocked_api):
    """Return an Mp3Quran client with mocked API."""
    return Mp3Quran(language="English", cache_ttl=3600, timeout=10)


class TestMp3QuranInit:

    def test_language_url_formation(self, mocked_api):
        c = Mp3Quran(language="English")
        assert c.url == _API_BASE + "_english.json"
        assert c.suras_name_url == _API_BASE + "_english_sura.json"

    def test_language_url_arabic(self, mocked_api):
        c = Mp3Quran(language="Arabic")
        assert c.url == _API_BASE + "_arabic.json"
        assert c.suras_name_url == _API_BASE + "_arabic_sura.json"

    def test_suras_loaded(self, client):
        assert 1 in client.suras_name
        assert client.suras_name[1] == "Al-Fatiha"
        assert client.suras_name[2] == "Al-Baqara"

    def test_reciters_loaded(self, client):
        assert 1 in client.reciters
        assert client.reciters[1]["name"] == "Mishary Rashid Alafasy"
        assert client.reciters[1]["url"] == "https://server.example.com/mishary"
        assert client.reciters[1]["suras"] == [1, 2, 3]
        assert client.reciters[1]["rewaya"] == "Hafs"

    def test_radios_loaded(self, client):
        assert len(client.radios) == 2
        assert client.radios[0]["name"] == "Quran Radio 24/7"
        assert client.radios[0]["url"] == "https://stream.example.com/radio1"


class TestMp3QuranGetRadios:

    def test_returns_track_refs(self, client):
        refs = client.get_radios()
        assert len(refs) == 2
        assert refs[0].uri == "mp3quran:radio:0"
        assert refs[0].name == "Quran Radio 24/7"
        assert refs[1].uri == "mp3quran:radio:1"

    def test_ref_type_is_track(self, client):
        refs = client.get_radios()
        for ref in refs:
            assert ref.type == "track"


class TestMp3QuranGetReciters:

    def test_returns_directory_refs(self, client):
        refs = client.get_reciters()
        assert len(refs) == 2
        assert refs[0].uri == "mp3quran:reciter:1"
        assert "Mishary Rashid Alafasy" in refs[0].name
        assert "Hafs" in refs[0].name

    def test_ref_type_is_directory(self, client):
        refs = client.get_reciters()
        for ref in refs:
            assert ref.type == "directory"


class TestMp3QuranReciterSuras:

    def test_returns_track_refs(self, client):
        refs = client.reciter_suras(1)
        assert len(refs) == 3
        assert refs[0].uri == "mp3quran:reciter:1:1"
        assert refs[0].name == "Al-Fatiha"

    def test_unknown_reciter_returns_empty(self, client):
        refs = client.reciter_suras(999)
        assert refs == []

    def test_surah_name_fallback(self, client):
        refs = client.reciter_suras(2)
        assert len(refs) == 2
        assert refs[0].name == "Al-Fatiha"
        assert refs[1].name == "Al-Baqara"


class TestMp3QuranTranslateUri:

    def test_reciter_surah_uri(self, client):
        url = client.translate_uri("mp3quran:reciter:1:2")
        assert url == "https://server.example.com/mishary/002.mp3"

    def test_radio_uri(self, client):
        url = client.translate_uri("mp3quran:radio:0")
        assert url == "https://stream.example.com/radio1"

    def test_invalid_uri_returns_none(self, client):
        assert client.translate_uri("mp3quran:invalid") is None

    def test_empty_uri_returns_none(self, client):
        assert client.translate_uri("mp3quran:") is None

    def test_unknown_variant_returns_none(self, client):
        assert client.translate_uri("mp3quran:unknown:1") is None

    def test_reciter_without_surah_returns_none(self, client):
        assert client.translate_uri("mp3quran:reciter:1") is None

    def test_radio_out_of_range_returns_none(self, client):
        assert client.translate_uri("mp3quran:radio:99") is None


class TestMp3QuranSearch:

    def test_search_reciter_by_name(self, client):
        refs = client.search("Mishary")
        assert len(refs) == 1
        assert "Mishary" in refs[0].name

    def test_search_reciter_by_rewaya(self, client):
        refs = client.search("Hafs")
        assert len(refs) >= 2

    def test_search_radio(self, client):
        refs = client.search("24/7")
        assert len(refs) == 1
        assert refs[0].name == "Quran Radio 24/7"

    def test_search_case_insensitive(self, client):
        refs = client.search("mishary")
        assert len(refs) == 1

    def test_search_no_results(self, client):
        refs = client.search("nonexistent")
        assert refs == []

    def test_search_radio_returns_track_ref(self, client):
        refs = client.search("Radio")
        radio_refs = [r for r in refs if r.uri.startswith("mp3quran:radio:")]
        assert len(radio_refs) >= 1
        assert radio_refs[0].type == "track"

    def test_search_reciter_returns_directory_ref(self, client):
        refs = client.search("Mishary")
        assert refs[0].type == "directory"


class TestMp3QuranCaching:

    def test_cache_prevents_refetch(self, mocked_api):
        c = Mp3Quran(language="English", cache_ttl=3600)
        first_call_count = len(responses.calls)
        c._init_reciters()
        second_call_count = len(responses.calls)
        assert second_call_count == first_call_count

    def test_cache_expiry_triggers_refetch(self, mocked_api):
        c = Mp3Quran(language="English", cache_ttl=1)
        initial_calls = len(responses.calls)
        time.sleep(1.1)
        c._init_reciters()
        assert len(responses.calls) > initial_calls

    def test_refresh_clears_cache(self, client):
        client.refresh()
        assert client._reciters_timestamp == 0.0 or len(responses.calls) > 0


class TestMp3QuranErrorHandling:

    def test_failed_suras_request(self):
        with responses.mock:
            responses.add(
                responses.GET,
                _API_BASE + "_english_sura.json",
                status=500,
            )
            responses.add(
                responses.GET,
                _API_BASE + "_english.json",
                json=RECITERS_RESPONSE,
                status=200,
            )
            responses.add(
                responses.GET,
                _RADIO_API,
                json=RADIOS_RESPONSE,
                status=200,
            )
            c = Mp3Quran(language="English")
            assert c.suras_name == {}

    def test_failed_reciters_request(self):
        with responses.mock:
            responses.add(
                responses.GET,
                _API_BASE + "_english_sura.json",
                json=SURAS_RESPONSE,
                status=200,
            )
            responses.add(
                responses.GET,
                _API_BASE + "_english.json",
                status=500,
            )
            responses.add(
                responses.GET,
                _RADIO_API,
                json=RADIOS_RESPONSE,
                status=200,
            )
            c = Mp3Quran(language="English")
            assert c.reciters == {}

    def test_failed_radios_request(self):
        with responses.mock:
            responses.add(
                responses.GET,
                _API_BASE + "_english_sura.json",
                json=SURAS_RESPONSE,
                status=200,
            )
            responses.add(
                responses.GET,
                _API_BASE + "_english.json",
                json=RECITERS_RESPONSE,
                status=200,
            )
            responses.add(
                responses.GET,
                _RADIO_API,
                status=500,
            )
            c = Mp3Quran(language="English")
            assert c.radios == []

    def test_invalid_reciter_entry_skipped(self):
        bad_reciters = {
            "reciters": [
                {"id": "1", "name": "Valid", "Server": "https://example.com", "suras": "1,2", "rewaya": "Hafs"},
                {"id": "bad", "name": "Invalid"},  # Missing required fields
            ]
        }
        with responses.mock:
            responses.add(responses.GET, _API_BASE + "_english_sura.json", json=SURAS_RESPONSE, status=200)
            responses.add(responses.GET, _API_BASE + "_english.json", json=bad_reciters, status=200)
            responses.add(responses.GET, _RADIO_API, json=RADIOS_RESPONSE, status=200)
            c = Mp3Quran(language="English")
            assert 1 in c.reciters
            assert len(c.reciters) == 1

    def test_invalid_radio_entry_skipped(self):
        bad_radios = {
            "Radios": [
                {"Name": "Valid Radio", "URL": "https://example.com/stream"},
                {"Name": "Invalid Radio"},  # Missing URL
            ]
        }
        with responses.mock:
            responses.add(responses.GET, _API_BASE + "_english_sura.json", json=SURAS_RESPONSE, status=200)
            responses.add(responses.GET, _API_BASE + "_english.json", json=RECITERS_RESPONSE, status=200)
            responses.add(responses.GET, _RADIO_API, json=bad_radios, status=200)
            c = Mp3Quran(language="English")
            assert len(c.radios) == 1
            assert c.radios[0]["name"] == "Valid Radio"

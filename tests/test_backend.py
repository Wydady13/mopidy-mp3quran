from unittest import mock

import pytest
import responses

from mopidy.models import Ref, Track, Artist, SearchResult
from mopidy_mp3quran.backend import (
    Mp3QuranBackend,
    Mp3QuranLibraryProvider,
    Mp3QuranPlaybackProvider,
    get_requests_session,
)
from mopidy_mp3quran.client import Mp3Quran, _API_BASE, _RADIO_API


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
    ]
}

RADIOS_RESPONSE = {
    "Radios": [
        {"Name": "Quran Radio 24/7", "URL": "https://stream.example.com/radio1"},
    ]
}


@pytest.fixture
def mock_config():
    return {
        "proxy": {"hostname": "", "port": "", "username": "", "password": ""},
        "mp3quran": {
            "enabled": True,
            "language": "English",
            "cache_ttl": 3600,
            "timeout": 10,
        },
    }


@pytest.fixture
def mock_audio():
    return mock.Mock()


@pytest.fixture
def mocked_api():
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
def backend(mocked_api, mock_config, mock_audio):
    return Mp3QuranBackend(config=mock_config, audio=mock_audio)


@pytest.fixture
def library(backend):
    return backend.library


@pytest.fixture
def playback(backend):
    return backend.playback


class TestMp3QuranBackend:

    def test_uri_schemes(self, backend):
        assert backend.uri_schemes == ["mp3quran"]

    def test_has_library_provider(self, backend):
        assert isinstance(backend.library, Mp3QuranLibraryProvider)

    def test_has_playback_provider(self, backend):
        assert isinstance(backend.playback, Mp3QuranPlaybackProvider)

    def test_proxy_config_key(self, mock_config, mock_audio):
        """Verify that proxy config is passed from config['proxy'], not the full config."""
        with mock.patch("mopidy_mp3quran.backend.get_requests_session") as mock_session:
            mock_session.return_value = mock.Mock()
            with mock.patch("mopidy_mp3quran.backend.client.Mp3Quran"):
                Mp3QuranBackend(config=mock_config, audio=mock_audio)
            call_kwargs = mock_session.call_args
            assert call_kwargs[1]["proxy_config"] == mock_config["proxy"]


class TestGetRequestsSession:

    def test_passes_proxy_config(self):
        with mock.patch("mopidy.httpclient.format_proxy", return_value="http://proxy:8080"):
            with mock.patch("mopidy.httpclient.format_user_agent", return_value="TestAgent/1.0"):
                session = get_requests_session(
                    proxy_config={"hostname": "proxy", "port": "8080"},
                    user_agent="TestAgent/1.0",
                )
                assert "http" in session.proxies
                assert session.proxies["http"] == "http://proxy:8080"

    def test_sets_user_agent(self):
        with mock.patch("mopidy.httpclient.format_proxy", return_value=""):
            with mock.patch("mopidy.httpclient.format_user_agent", return_value="Mp3Quran/0.2"):
                session = get_requests_session(
                    proxy_config={},
                    user_agent="Mp3Quran/0.2",
                )
                assert session.headers["user-agent"] == "Mp3Quran/0.2"


class TestMp3QuranLibraryProvider:

    def test_root_directory(self, library):
        assert library.root_directory.uri == "mp3quran:root"
        assert library.root_directory.name == "Mp3Quran"

    def test_browse_root(self, library):
        results = library.browse("mp3quran:root")
        assert len(results) == 2
        assert results[0].uri == "mp3quran:reciters"
        assert results[1].uri == "mp3quran:radios"

    def test_browse_reciters(self, library):
        results = library.browse("mp3quran:reciters")
        assert len(results) == 1
        assert results[0].uri == "mp3quran:reciter:1"
        assert results[0].type == Ref.DIRECTORY

    def test_browse_reciter(self, library):
        results = library.browse("mp3quran:reciter:1")
        assert len(results) == 3
        assert results[0].uri == "mp3quran:reciter:1:1"
        assert results[0].name == "Al-Fatiha"
        assert results[0].type == Ref.TRACK

    def test_browse_radios(self, library):
        results = library.browse("mp3quran:radios")
        assert len(results) == 1
        assert results[0].uri == "mp3quran:radio:0"
        assert results[0].type == Ref.TRACK

    def test_browse_unknown_uri(self, library):
        results = library.browse("mp3quran:unknown")
        assert results == []

    def test_lookup_reciter_surah(self, library):
        tracks = library.lookup("mp3quran:reciter:1:2")
        assert len(tracks) == 1
        track = tracks[0]
        assert track.uri == "mp3quran:reciter:1:2"
        assert track.name == "Al-Baqara"
        assert any(a.name == "Mishary Rashid Alafasy" for a in track.artists)
        assert track.album.name == "Hafs"
        assert track.track_no == 2

    def test_lookup_radio(self, library):
        tracks = library.lookup("mp3quran:radio:0")
        assert len(tracks) == 1
        assert tracks[0].uri == "mp3quran:radio:0"
        assert tracks[0].name == "Quran Radio 24/7"

    def test_lookup_invalid_uri(self, library):
        tracks = library.lookup("mp3quran:")
        assert tracks == []

    def test_lookup_unknown_variant(self, library):
        tracks = library.lookup("mp3quran:unknown:1")
        assert tracks == []

    def test_lookup_nonexistent_reciter(self, library):
        tracks = library.lookup("mp3quran:reciter:999:1")
        assert tracks == []

    def test_lookup_nonexistent_radio(self, library):
        tracks = library.lookup("mp3quran:radio:99")
        assert tracks == []

    def test_lookup_invalid_identifier(self, library):
        tracks = library.lookup("mp3quran:reciter:abc")
        assert tracks == []

    def test_refresh(self, library):
        with mock.patch.object(library.backend.mp3quran, "refresh") as mock_refresh:
            library.refresh()
            mock_refresh.assert_called_once()


class TestMp3QuranLibrarySearch:

    def test_search_reciter(self, library):
        result = library.search(query="Mishary")
        assert isinstance(result, SearchResult)
        assert len(result.artists) == 1
        assert result.artists[0].name == "Mishary Rashid Alafasy"

    def test_search_radio(self, library):
        result = library.search(query="Radio")
        assert isinstance(result, SearchResult)
        assert len(result.tracks) >= 1

    def test_search_returns_both_tracks_and_artists(self, library):
        result = library.search(query="Hafs")
        assert len(result.artists) >= 1

    def test_search_none_query(self, library):
        result = library.search(query=None)
        assert result is None

    def test_search_empty_query(self, library):
        result = library.search(query="")
        assert result is None

    def test_search_dict_query(self, library):
        result = library.search(query={"any": "Mishary"})
        assert len(result.artists) >= 1

    def test_search_dict_query_multiple_values(self, library):
        result = library.search(query={"any": ["Mishary", "Alafasy"]})
        assert isinstance(result, SearchResult)

    def test_search_no_results(self, library):
        result = library.search(query="nonexistentxyz123")
        assert isinstance(result, SearchResult)
        assert len(result.tracks) == 0
        assert len(result.artists) == 0


class TestMp3QuranPlaybackProvider:

    def test_translate_uri_reciter(self, playback):
        url = playback.translate_uri("mp3quran:reciter:1:2")
        assert url == "https://server.example.com/mishary/002.mp3"

    def test_translate_uri_radio(self, playback):
        url = playback.translate_uri("mp3quran:radio:0")
        assert url == "https://stream.example.com/radio1"

    def test_translate_uri_invalid(self, playback):
        url = playback.translate_uri("mp3quran:invalid")
        assert url is None

    def test_is_live_radio(self, playback):
        assert playback.is_live("mp3quran:radio:0") is True

    def test_is_live_reciter(self, playback):
        assert playback.is_live("mp3quran:reciter:1:2") is False

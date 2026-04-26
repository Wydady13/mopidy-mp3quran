import logging
from typing import List, Optional

import requests as _requests
import pykka
import mopidy_mp3quran

from mopidy_mp3quran import client
from mopidy import backend, httpclient
from mopidy.models import Ref, Track, Album, Artist, SearchResult

logger = logging.getLogger(__name__)


def get_requests_session(proxy_config, user_agent: str) -> _requests.Session:
    """Create a requests session with proxy and user agent settings."""
    proxy = httpclient.format_proxy(proxy_config)
    full_user_agent = httpclient.format_user_agent(user_agent)

    session = _requests.Session()
    session.proxies.update({'http': proxy, 'https': proxy})
    session.headers.update({'user-agent': full_user_agent})

    return session


class Mp3QuranBackend(pykka.ThreadingActor, backend.Backend):
    """Backend for streaming Quran from mp3quran.net."""

    uri_schemes = ['mp3quran']

    def __init__(self, config, audio) -> None:
        super().__init__()

        self.audio = audio
        self.config = config
        self.session = get_requests_session(
            proxy_config=self.config["proxy"],
            user_agent='%s/%s' % (
                mopidy_mp3quran.Extension.dist_name,
                mopidy_mp3quran.__version__)
        )

        mp3quran_config = config.get('mp3quran', {})
        self.mp3quran = client.Mp3Quran(
            session=self.session,
            locale=mp3quran_config.get('language', client._DEFAULT_LOCALE),
            cache_ttl=mp3quran_config.get('cache_ttl', client._DEFAULT_CACHE_TTL),
            timeout=mp3quran_config.get('timeout', client._DEFAULT_TIMEOUT),
        )

        self.library = Mp3QuranLibraryProvider(backend=self)
        self.playback = Mp3QuranPlaybackProvider(audio=audio, backend=self)


class Mp3QuranLibraryProvider(backend.LibraryProvider):
    """Library provider for browsing Quran reciters and radios."""

    root_directory = Ref.directory(uri='mp3quran:root', name='Mp3Quran')

    def browse(self, uri: str) -> List[Ref]:
        """Browse the library at the given URI."""
        results = []
        parsed = uri.split(':')
        variant = parsed[1] if len(parsed) >= 2 else None
        identifier = parsed[2] if len(parsed) >= 3 else None
        extra = parsed[3] if len(parsed) >= 4 else None

        if variant == 'root':
            results.append(Ref.directory(uri='mp3quran:languages', name='Languages'))
            results.append(Ref.directory(uri='mp3quran:reciters', name='Reciters'))
            results.append(Ref.directory(uri='mp3quran:riwayat', name='Riwayat'))
            results.append(Ref.directory(uri='mp3quran:radios', name='Radios'))
            results.append(Ref.directory(uri='mp3quran:tafasir', name='Tafasir'))
        elif variant == 'languages':
            results = self.backend.mp3quran.get_languages()
        elif variant == 'language' and identifier:
            self.backend.mp3quran.set_locale(identifier)
            results = self.backend.mp3quran.get_reciters()
        elif variant == 'radios':
            results = self.backend.mp3quran.get_radios()
        elif variant == 'riwayat':
            results = self.backend.mp3quran.get_riwayat()
        elif variant == 'riwaya' and identifier:
            results = self.backend.mp3quran.riwaya_reciters(int(identifier))
        elif variant == 'tafasir':
            results = self.backend.mp3quran.get_tafasir()
        elif variant == 'tafsir' and identifier:
            results = self.backend.mp3quran.tafsir_audio(int(identifier))
        elif variant == 'reciters':
            results = self.backend.mp3quran.get_reciters()
        elif variant == 'reciter' and identifier:
            results = self.backend.mp3quran.reciter_moshaf(identifier)
        elif variant == 'moshaf' and identifier and extra:
            results = self.backend.mp3quran.moshaf_suras(int(identifier), int(extra))
        else:
            logger.debug('Unknown uri: %s at library.browse', uri)

        return results

    def refresh(self, uri: Optional[str] = None) -> None:
        self.backend.mp3quran.refresh()

    def lookup(self, uri: str) -> List[Track]:
        """Look up a track by URI."""
        tracks = []
        parsed_uri = uri.split(':')[1:]
        logger.debug('Looking up uri: %s', uri)

        if not parsed_uri or len(parsed_uri) < 2:
            logger.debug('Invalid uri format: %s', uri)
            return tracks

        try:
            variant = parsed_uri[0]
            if variant == 'reciter':
                if len(parsed_uri) != 4:
                    logger.debug('Invalid reciter uri format: %s', uri)
                    return tracks
                reciter_id = int(parsed_uri[1])
                moshaf_id = int(parsed_uri[2])
                sura_no = int(parsed_uri[3])
            elif variant == 'radio':
                radio_id = int(parsed_uri[1])
            elif variant == 'tafsir_audio':
                if len(parsed_uri) != 3:
                    logger.debug('Invalid tafsir_audio uri format: %s', uri)
                    return tracks
                tafsir_id = int(parsed_uri[1])
                audio_id = int(parsed_uri[2])
            else:
                logger.debug('Unknown variant in uri: %s', uri)
                return tracks
        except (ValueError, IndexError) as e:
            logger.debug('Invalid uri %s: %s', uri, e)
            return tracks

        if variant == 'reciter':
            if reciter_id not in self.backend.mp3quran.reciters:
                logger.debug('Reciter ID %d not found', reciter_id)
                return tracks
            reciter = self.backend.mp3quran.reciters[reciter_id]
            moshaf_found = None
            for moshaf in reciter['moshaf']:
                if moshaf['id'] == moshaf_id:
                    moshaf_found = moshaf
                    break
            if moshaf_found is None:
                logger.debug('Moshaf ID %d not found for reciter %d', moshaf_id, reciter_id)
                return tracks
            sura_name = self.backend.mp3quran.suras_name.get(sura_no, 'Surah %d' % sura_no)
            artists = [Artist(name=reciter['name'])]
            album = Album(name=moshaf_found['name'])
            tracks.append(Track(
                uri=uri, name=sura_name,
                artists=artists, album=album, track_no=sura_no,
            ))
        elif variant == 'radio':
            if radio_id in self.backend.mp3quran.radios:
                radio = self.backend.mp3quran.radios[radio_id]
                tracks.append(Track(uri=uri, name=radio['name']))
            else:
                logger.debug('Radio ID %d not found', radio_id)
        elif variant == 'tafsir_audio':
            url = self.backend.mp3quran.translate_tafsir_uri(tafsir_id, audio_id)
            if url:
                tafsir_name = self.backend.mp3quran.tafasir.get(tafsir_id, {}).get('name', 'Tafsir')
                tracks.append(Track(uri=uri, name=tafsir_name, album=Album(name=tafsir_name)))
            else:
                logger.debug('Tafsir audio %d/%d not found', tafsir_id, audio_id)

        return tracks

    def search(self, query=None, uris=None, exact=False) -> SearchResult:
        if query is None:
            return None

        if isinstance(query, dict):
            query_str = ' '.join(
                v for vals in query.values() for v in (vals if isinstance(vals, list) else [vals])
            )
        else:
            query_str = str(query)

        if not query_str.strip():
            return None

        results = self.backend.mp3quran.search(query_str)
        tracks = []
        artists = []
        for ref in results:
            if ref.type == Ref.TRACK:
                lookup_tracks = self.lookup(ref.uri)
                tracks.extend(lookup_tracks)
            elif ref.type == Ref.DIRECTORY and ref.uri.startswith('mp3quran:reciter:'):
                try:
                    reciter_id = int(ref.uri.split(':')[2])
                    reciter = self.backend.mp3quran.reciters[reciter_id]
                    artists.append(Artist(name=reciter['name']))
                except (IndexError, ValueError, KeyError):
                    logger.debug('Could not extract artist from ref: %s', ref.uri)

        return SearchResult(tracks=tracks, artists=artists)


class Mp3QuranPlaybackProvider(backend.PlaybackProvider):

    def __init__(self, audio, backend) -> None:
        super().__init__(audio, backend)
        self.config = backend.config
        self.session = backend.session

    def translate_uri(self, uri: str) -> Optional[str]:
        url = self.backend.mp3quran.translate_uri(uri)
        if url:
            logger.info('Mp3Quran: Stream URL: %s', url)
            return url
        else:
            logger.debug('URI could not be translated: %s', uri)
            return None

    def is_live(self, uri: str) -> bool:
        return uri.startswith('mp3quran:radio:')

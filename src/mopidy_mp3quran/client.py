import time
import logging
from typing import Dict, List, Optional, Any

import requests
from mopidy.models import Ref

logger = logging.getLogger(__name__)

_API_BASE = 'https://mp3quran.net/api/v3/'
_DEFAULT_CACHE_TTL = 3600  # 1 hour
_DEFAULT_TIMEOUT = 10  # seconds
_DEFAULT_LOCALE = 'eng'


class Mp3Quran:
    """Client for the mp3quran.net v3 REST API with caching."""

    def __init__(
        self,
        session: requests.Session = None,
        locale: str = _DEFAULT_LOCALE,
        cache_ttl: int = _DEFAULT_CACHE_TTL,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self.session = session or requests.Session()
        self.cache_ttl = cache_ttl
        self.timeout = timeout

        self.languages: List[Dict[str, str]] = []
        self.reciters: Dict[int, Dict[str, Any]] = {}
        self.radios: Dict[int, Dict[str, str]] = {}
        self.suras_name: Dict[int, str] = {}
        self.riwayat: Dict[int, str] = {}
        self.tafasir: Dict[int, Dict[str, Any]] = {}

        self._languages_timestamp: float = 0.0
        self._reciters_timestamp: float = 0.0
        self._radios_timestamp: float = 0.0
        self._suras_timestamp: float = 0.0
        self._riwayat_timestamp: float = 0.0
        self._tafasir_timestamp: float = 0.0

        self._current_locale: str = ''

        self._init_languages()
        self.set_locale(locale)

    @property
    def locale(self) -> str:
        return self._current_locale

    def resolve_language(self, name: str) -> str:
        """Resolve a language name or locale code to a canonical locale code.

        Accepts both long form (e.g. 'English', 'arabic') and short form
        (e.g. 'eng', 'AR'). Case-insensitive. Returns the locale as-is if
        no match is found (may be a valid locale the API hasn't listed yet).
        """
        lower = name.lower().strip()
        for lang in self.languages:
            if lang['locale'].lower() == lower or lang['name'].lower() == lower:
                return lang['locale']
        return lower

    def _get_lang_url(self, key: str) -> str:
        """Get the API URL for the current language by key."""
        return _API_BASE + key + '?language=' + self._current_locale

    def set_locale(self, locale: str) -> None:
        """Switch to a different locale and reload reciters/suras/radios.

        Accepts both locale codes ('eng') and full names ('English'),
        case-insensitive.
        """
        resolved = self.resolve_language(locale)
        self._current_locale = resolved
        self.reciters = {}
        self.radios = {}
        self.suras_name = {}
        self.riwayat = {}
        self.tafasir = {}
        self._reciters_timestamp = 0.0
        self._radios_timestamp = 0.0
        self._suras_timestamp = 0.0
        self._riwayat_timestamp = 0.0
        self._tafasir_timestamp = 0.0
        self._init_suras()
        self._init_riwayat()
        self._init_reciters()
        self._init_radios()
        self._init_tafasir()

    def _is_cache_valid(self, timestamp: float) -> bool:
        if timestamp == 0.0:
            return False
        return (time.time() - timestamp) < self.cache_ttl

    def _fetch(self, url: str) -> Optional[dict]:
        """Fetch JSON from a URL with error handling."""
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error('Mp3Quran: Failed to fetch %s: %s', url, e)
            return None
        except (KeyError, ValueError) as e:
            logger.error('Mp3Quran: Invalid data from %s: %s', url, e)
            return None

    def _init_languages(self) -> None:
        if self._is_cache_valid(self._languages_timestamp):
            return
        data = self._fetch(_API_BASE + 'languages')
        if data is None:
            return
        self.languages = []
        for lang in data.get('language', []):
            try:
                self.languages.append({
                    'id': lang['id'],
                    'name': lang['language'],
                    'native': lang.get('native', ''),
                    'locale': lang['locale'],
                })
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid language entry: %s', e)
                continue
        self._languages_timestamp = time.time()

    def _init_suras(self) -> None:
        if self._is_cache_valid(self._suras_timestamp):
            return
        url = self._get_lang_url('suwar')
        data = self._fetch(url)
        if data is None:
            return
        for sura in data.get('suwar', []):
            try:
                name = sura['name'].strip()
                self.suras_name[int(sura['id'])] = name
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid surah entry: %s', e)
                continue
        self._suras_timestamp = time.time()

    def _init_riwayat(self) -> None:
        if self._is_cache_valid(self._riwayat_timestamp):
            return
        url = self._get_lang_url('riwayat')
        data = self._fetch(url)
        if data is None:
            return
        for r in data.get('riwayat', []):
            try:
                self.riwayat[int(r['id'])] = r['name']
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid riwayat entry: %s', e)
                continue
        self._riwayat_timestamp = time.time()

    def _init_reciters(self) -> None:
        if self._is_cache_valid(self._reciters_timestamp):
            return
        url = self._get_lang_url('reciters')
        data = self._fetch(url)
        if data is None:
            return
        for reciter in data.get('reciters', []):
            try:
                moshaf_list = []
                has_valid_moshaf = False
                for m in reciter.get('moshaf', []):
                    try:
                        sura_ids = [int(n) for n in m['surah_list'].split(',') if n.strip()]
                        moshaf_list.append({
                            'id': int(m['id']),
                            'name': m['name'],
                            'rewaya_id': int(m.get('rewaya_id', 0)),
                            'server': m['server'],
                            'surah_total': int(m.get('surah_total', 0)),
                            'moshaf_type': int(m.get('moshaf_type', 0)),
                            'surah_list': sura_ids,
                        })
                        has_valid_moshaf = True
                    except (KeyError, ValueError) as e:
                        logger.warning('Mp3Quran: Skipping invalid moshaf entry: %s', e)
                        continue
                if not has_valid_moshaf:
                    logger.warning('Mp3Quran: Skipping reciter with no valid moshaf: %s', reciter.get('name', '?'))
                    continue
                self.reciters[int(reciter['id'])] = {
                    'name': reciter['name'],
                    'letter': reciter.get('letter', ''),
                    'date': reciter.get('date', ''),
                    'moshaf': moshaf_list,
                }
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid reciter entry: %s', e)
                continue
        self._reciters_timestamp = time.time()

    def _init_tafasir(self) -> None:
        if self._is_cache_valid(self._tafasir_timestamp):
            return
        url = self._get_lang_url('tafasir')
        data = self._fetch(url)
        if data is None:
            return
        for t in data.get('tafasir', []):
            try:
                self.tafasir[int(t['id'])] = {
                    'name': t['name'],
                    'url': t['url'],
                }
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid tafsir entry: %s', e)
                continue
        self._tafasir_timestamp = time.time()

    def _init_radios(self) -> None:
        if self._is_cache_valid(self._radios_timestamp):
            return
        url = self._get_lang_url('radios')
        data = self._fetch(url)
        if data is None:
            return
        for radio in data.get('radios', []):
            try:
                self.radios[int(radio['id'])] = {
                    'name': radio['name'],
                    'url': radio['url'],
                }
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid radio entry: %s', e)
                continue
        self._radios_timestamp = time.time()

    def translate_uri(self, uri: str) -> Optional[str]:
        """Translate a mopidy URI to a streaming URL."""
        parsed = uri.split(':')[1:]
        if not parsed:
            logger.debug('Could not translate uri: %s', uri)
            return None

        try:
            variant = parsed[0]
            if variant == 'reciter' and len(parsed) == 4:
                reciter_id = int(parsed[1])
                moshaf_id = int(parsed[2])
                sura_no = int(parsed[3])
            elif variant == 'radio' and len(parsed) == 2:
                radio_id = int(parsed[1])
            elif variant == 'tafsir_audio' and len(parsed) == 3:
                tafsir_id = int(parsed[1])
                audio_id = int(parsed[2])
            else:
                logger.debug('Invalid uri format: %s', uri)
                return None
        except (ValueError, IndexError) as e:
            logger.debug('Invalid uri format %s: %s', uri, e)
            return None

        if variant == 'reciter':
            if reciter_id not in self.reciters:
                logger.debug('Reciter ID %d not found', reciter_id)
                return None
            for moshaf in self.reciters[reciter_id]['moshaf']:
                if moshaf['id'] == moshaf_id and sura_no in moshaf['surah_list']:
                    return moshaf['server'].rstrip('/') + '/%03d' % sura_no + '.mp3'
            logger.debug('Moshaf %d or surah %d not found for reciter %d', moshaf_id, sura_no, reciter_id)
            return None
        elif variant == 'radio':
            if radio_id in self.radios:
                return self.radios[radio_id]['url']
            logger.debug('Radio ID %d not found', radio_id)
            return None
        elif variant == 'tafsir_audio':
            url = self.translate_tafsir_uri(tafsir_id, audio_id)
            if url:
                return url
            logger.debug('Tafsir audio %d/%d not found', tafsir_id, audio_id)
            return None

        logger.debug('Could not translate uri: %s', uri)
        return None

    def get_riwayat(self) -> List[Ref]:
        results = []
        for riwaya_id, name in self.riwayat.items():
            reciters_with_riwaya = [
                (rid, r) for rid, r in self.reciters.items()
                if any(m['rewaya_id'] == riwaya_id for m in r['moshaf'])
            ]
            if reciters_with_riwaya:
                results.append(Ref.directory(
                    uri='mp3quran:riwaya:%d' % riwaya_id, name=name,
                ))
        return results

    def riwaya_reciters(self, riwaya_id: int) -> List[Ref]:
        results = []
        riwaya_id = int(riwaya_id)
        for reciter_id, reciter in self.reciters.items():
            for moshaf in reciter['moshaf']:
                if moshaf['rewaya_id'] == riwaya_id:
                    results.append(
                        Ref.directory(
                            uri='mp3quran:moshaf:%d:%d' % (reciter_id, moshaf['id']),
                            name='%s - %s' % (reciter['name'], moshaf['name']),
                        )
                    )
                    break
        return results

    def get_tafasir(self) -> List[Ref]:
        results = []
        for tafsir_id, tafsir in self.tafasir.items():
            results.append(Ref.directory(
                uri='mp3quran:tafsir:%d' % tafsir_id, name=tafsir['name'],
            ))
        return results

    def tafsir_audio(self, tafsir_id: int) -> List[Ref]:
        results = []
        tafsir_id = int(tafsir_id)
        if tafsir_id not in self.tafasir:
            logger.warning('Mp3Quran: Tafsir ID %d not found', tafsir_id)
            return results
        url = _API_BASE + 'tafsir?tafsir=%d&language=%s' % (tafsir_id, self._current_locale)
        data = self._fetch(url)
        if data is None:
            return results
        tafsir_data = data.get('tafasir', {})
        for audio in tafsir_data.get('soar', []):
            try:
                results.append(Ref.track(
                    uri='mp3quran:tafsir_audio:%d:%d' % (tafsir_id, int(audio['id'])),
                    name=audio['name'],
                ))
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid tafsir audio entry: %s', e)
                continue
        return results

    def translate_tafsir_uri(self, tafsir_id: int, audio_id: int) -> Optional[str]:
        tafsir_id = int(tafsir_id)
        audio_id = int(audio_id)
        if tafsir_id not in self.tafasir:
            return None
        url = _API_BASE + 'tafsir?tafsir=%d&language=%s' % (tafsir_id, self._current_locale)
        data = self._fetch(url)
        if data is None:
            return None
        for audio in data.get('tafasir', {}).get('soar', []):
            if int(audio['id']) == audio_id:
                return audio['url']
        return None

    def get_languages(self) -> List[Ref]:
        results = []
        for lang in self.languages:
            results.append(Ref.directory(
                uri='mp3quran:language:' + lang['locale'],
                name=lang['name'],
            ))
        return results

    def get_radios(self) -> List[Ref]:
        results = []
        for radio_id, radio in self.radios.items():
            results.append(Ref.track(uri='mp3quran:radio:%d' % radio_id, name=radio['name']))
        return results

    def get_reciters(self) -> List[Ref]:
        results = []
        for reciter_id, reciter in self.reciters.items():
            results.append(Ref.directory(uri='mp3quran:reciter:%d' % reciter_id, name=reciter['name']))
        return results

    def reciter_moshaf(self, reciter_id: int) -> List[Ref]:
        """Return moshaf (recitation versions) for a reciter."""
        results = []
        reciter_id = int(reciter_id)
        if reciter_id not in self.reciters:
            logger.warning('Mp3Quran: Reciter ID %d not found', reciter_id)
            return results
        reciter = self.reciters[reciter_id]
        for moshaf in reciter['moshaf']:
            results.append(
                Ref.directory(
                    uri='mp3quran:moshaf:%d:%d' % (reciter_id, moshaf['id']),
                    name=moshaf['name'],
                )
            )
        return results

    def moshaf_suras(self, reciter_id: int, moshaf_id: int) -> List[Ref]:
        """Return surahs for a specific moshaf of a reciter."""
        results = []
        reciter_id = int(reciter_id)
        moshaf_id = int(moshaf_id)
        if reciter_id not in self.reciters:
            logger.warning('Mp3Quran: Reciter ID %d not found', reciter_id)
            return results
        reciter = self.reciters[reciter_id]
        for moshaf in reciter['moshaf']:
            if moshaf['id'] == moshaf_id:
                for sura_no in moshaf['surah_list']:
                    sura_name = self.suras_name.get(sura_no, 'Surah %d' % sura_no)
                    results.append(
                        Ref.track(
                            uri='mp3quran:reciter:%d:%d:%d' % (reciter_id, moshaf_id, sura_no),
                            name=sura_name,
                        )
                    )
                return results
        logger.warning('Mp3Quran: Moshaf ID %d not found for reciter %d', moshaf_id, reciter_id)
        return results

    def search(self, query: str) -> List[Ref]:
        """Search reciters and radios by name (case-insensitive)."""
        results = []
        query_lower = query.lower()
        for reciter_id, reciter in self.reciters.items():
            if query_lower in reciter['name'].lower():
                results.append(Ref.directory(uri='mp3quran:reciter:%d' % reciter_id, name=reciter['name']))
            else:
                for moshaf in reciter['moshaf']:
                    if query_lower in moshaf['name'].lower():
                        results.append(Ref.directory(uri='mp3quran:reciter:%d' % reciter_id, name=reciter['name']))
                        break
        for radio_id, radio in self.radios.items():
            if query_lower in radio['name'].lower():
                results.append(Ref.track(uri='mp3quran:radio:%d' % radio_id, name=radio['name']))
        return results

    def refresh(self) -> None:
        """Force re-fetch all data from the API."""
        self.languages = []
        self.reciters = {}
        self.radios = {}
        self.suras_name = {}
        self.riwayat = {}
        self.tafasir = {}
        self._languages_timestamp = 0.0
        self._reciters_timestamp = 0.0
        self._radios_timestamp = 0.0
        self._suras_timestamp = 0.0
        self._riwayat_timestamp = 0.0
        self._tafasir_timestamp = 0.0
        self._init_languages()
        self._init_suras()
        self._init_riwayat()
        self._init_reciters()
        self._init_radios()
        self._init_tafasir()

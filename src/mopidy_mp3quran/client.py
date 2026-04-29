import json
import os
import time
import logging
from typing import Dict, List, Optional, Any

import requests
from mopidy.models import Ref

try:
    from rapidfuzz import fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False
    def fuzz_partial_ratio(a, b):
        return 100 if a.lower() in b.lower() else 0

logger = logging.getLogger(__name__)

_API_BASE = 'https://mp3quran.net/api/v3/'
_DEFAULT_CACHE_TTL = 3600
_DEFAULT_TIMEOUT = 10
_DEFAULT_LOCALE = 'eng'
_DEFAULT_FUZZY_THRESHOLD = 60
_DEFAULT_SEARCH_LIMIT = 50
_DEFAULT_RECENTLY_PLAYED_PATH = os.path.join(os.path.expanduser('~'), '.local', 'share', 'mopidy-mp3quran', 'recently_played.json')


class _LocaleData:
    __slots__ = ('reciters', 'radios', 'suras_name', 'riwayat', 'tafasir',
                 'reciters_ts', 'radios_ts', 'suras_ts', 'riwayat_ts', 'tafasir_ts')

    def __init__(self):
        self.reciters: Dict[int, Dict[str, Any]] = {}
        self.radios: Dict[int, Dict[str, str]] = {}
        self.suras_name: Dict[int, str] = {}
        self.riwayat: Dict[int, str] = {}
        self.tafasir: Dict[int, Dict[str, Any]] = {}
        self.reciters_ts: float = 0.0
        self.radios_ts: float = 0.0
        self.suras_ts: float = 0.0
        self.riwayat_ts: float = 0.0
        self.tafasir_ts: float = 0.0


class Mp3Quran:
    def __init__(
        self,
        session: requests.Session = None,
        cache_ttl: int = _DEFAULT_CACHE_TTL,
        timeout: int = _DEFAULT_TIMEOUT,
        validate_stream_url: bool = False,
        fuzzy_threshold: int = None,
        search_limit: int = None,
        recently_played_path: str = None,
    ) -> None:
        self.session = session or requests.Session()
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self._validate_stream_url = validate_stream_url
        self.fuzzy_threshold = fuzzy_threshold if fuzzy_threshold is not None else _DEFAULT_FUZZY_THRESHOLD
        self.search_limit = search_limit if search_limit is not None else _DEFAULT_SEARCH_LIMIT
        self.recently_played_path = recently_played_path or _DEFAULT_RECENTLY_PLAYED_PATH

        self.languages: List[Dict[str, str]] = []
        self._languages_timestamp: float = 0.0
        self._locales: Dict[str, _LocaleData] = {}
        self._recently_played: Dict[str, Any] = self._load_recently_played()

        self._init_languages()

    def resolve_language(self, name: str) -> str:
        lower = name.lower().strip()
        for lang in self.languages:
            if lang['locale'].lower() == lower or lang['name'].lower() == lower:
                return lang['locale']
        return lower

    def _get_locale_data(self, locale: str) -> _LocaleData:
        if locale not in self._locales:
            self._locales[locale] = _LocaleData()
        return self._locales[locale]

    def _ensure_loaded(self, locale: str, data: _LocaleData = None) -> None:
        if data is None:
            data = self._get_locale_data(locale)
        self._init_suras(locale, data)
        self._init_riwayat(locale, data)
        self._init_reciters(locale, data)
        self._init_radios(locale, data)
        self._init_tafasir(locale, data)

    def _is_cache_valid(self, timestamp: float) -> bool:
        if timestamp == 0.0:
            return False
        return (time.time() - timestamp) < self.cache_ttl

    def _fetch(self, url: str) -> Optional[dict]:
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

    def _init_suras(self, locale: str, data: _LocaleData) -> None:
        if self._is_cache_valid(data.suras_ts):
            return
        url = _API_BASE + 'suwar?language=' + locale
        resp = self._fetch(url)
        if resp is None:
            return
        for sura in resp.get('suwar', []):
            try:
                name = sura['name'].strip()
                data.suras_name[int(sura['id'])] = name
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid surah entry: %s', e)
                continue
        data.suras_ts = time.time()

    def _init_riwayat(self, locale: str, data: _LocaleData) -> None:
        if self._is_cache_valid(data.riwayat_ts):
            return
        url = _API_BASE + 'riwayat?language=' + locale
        resp = self._fetch(url)
        if resp is None:
            return
        for r in resp.get('riwayat', []):
            try:
                data.riwayat[int(r['id'])] = r['name']
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid riwayat entry: %s', e)
                continue
        data.riwayat_ts = time.time()

    def _init_reciters(self, locale: str, data: _LocaleData) -> None:
        if self._is_cache_valid(data.reciters_ts):
            return
        url = _API_BASE + 'reciters?language=' + locale
        resp = self._fetch(url)
        if resp is None:
            return
        for reciter in resp.get('reciters', []):
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
                data.reciters[int(reciter['id'])] = {
                    'name': reciter['name'],
                    'letter': reciter.get('letter', ''),
                    'date': reciter.get('date', ''),
                    'moshaf': moshaf_list,
                }
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid reciter entry: %s', e)
                continue
        data.reciters_ts = time.time()

    def _init_tafasir(self, locale: str, data: _LocaleData) -> None:
        if self._is_cache_valid(data.tafasir_ts):
            return
        url = _API_BASE + 'tafasir?language=' + locale
        resp = self._fetch(url)
        if resp is None:
            return
        for t in resp.get('tafasir', []):
            try:
                data.tafasir[int(t['id'])] = {
                    'name': t['name'],
                    'url': t['url'],
                }
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid tafsir entry: %s', e)
                continue
        data.tafasir_ts = time.time()

    def _init_radios(self, locale: str, data: _LocaleData) -> None:
        if self._is_cache_valid(data.radios_ts):
            return
        url = _API_BASE + 'radios?language=' + locale
        resp = self._fetch(url)
        if resp is None:
            return
        for radio in resp.get('radios', []):
            try:
                data.radios[int(radio['id'])] = {
                    'name': radio['name'],
                    'url': radio['url'],
                }
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid radio entry: %s', e)
                continue
        data.radios_ts = time.time()

    def _is_url_accessible(self, url: str) -> bool:
        try:
            response = self.session.head(url, timeout=self.timeout, allow_redirects=True)
            if response.status_code < 400:
                return True
            response = self.session.get(
                url,
                timeout=self.timeout,
                stream=True,
                headers={"Range": "bytes=0-0"},
            )
            try:
                return response.status_code < 400
            finally:
                response.close()
        except requests.RequestException:
            return False

    def _score_query(self, query: str, target: str) -> int:
        if _HAS_RAPIDFUZZ:
            return fuzz.partial_ratio(query.lower(), target.lower())
        else:
            return fuzz_partial_ratio(query.lower(), target.lower())

    def _load_recently_played(self) -> Dict[str, Any]:
        if not os.path.exists(self.recently_played_path):
            return {}
        try:
            with open(self.recently_played_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning('Mp3Quran: Failed to load recently played: %s', e)
            return {}

    def _save_recently_played(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.recently_played_path), exist_ok=True)
            with open(self.recently_played_path, 'w', encoding='utf-8') as f:
                json.dump(self._recently_played, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error('Mp3Quran: Failed to save recently played: %s', e)

    def get_recently_played(self) -> Optional[Dict[str, Any]]:
        return self._recently_played.get('last') if self._recently_played else None

    def set_recently_played(self, uri: str, name: str, variant: str, locale: str = None, reciter_id: int = None, moshaf_id: int = None, sura_no: int = None, radio_id: int = None, tafsir_id: int = None, audio_id: int = None) -> None:
        self._recently_played['last'] = {
            'uri': uri,
            'name': name,
            'variant': variant,
            'locale': locale,
            'reciter_id': reciter_id,
            'moshaf_id': moshaf_id,
            'sura_no': sura_no,
            'radio_id': radio_id,
            'tafsir_id': tafsir_id,
            'audio_id': audio_id,
            'timestamp': time.time(),
        }
        self._save_recently_played()

    def translate_uri(self, uri: str) -> Optional[str]:
        parsed = uri.split(':')[1:]
        if not parsed:
            logger.debug('Mp3Quran: Could not translate URI: %s', uri)
            return None

        try:
            locale = parsed[0]
            variant = parsed[1]
            if variant == 'reciter' and len(parsed) == 5:
                reciter_id = int(parsed[2])
                moshaf_id = int(parsed[3])
                sura_no = int(parsed[4])
            elif variant == 'radio' and len(parsed) == 3:
                radio_id = int(parsed[2])
            elif variant == 'tafsir_audio' and len(parsed) == 4:
                tafsir_id = int(parsed[2])
                audio_id = int(parsed[3])
            else:
                logger.debug('Mp3Quran: Invalid URI format: %s', uri)
                return None
        except (ValueError, IndexError) as e:
            logger.debug('Mp3Quran: Invalid URI format %s: %s', uri, e)
            return None

        data = self._get_locale_data(locale)

        if variant == 'reciter':
            self._init_reciters(locale, data)
            if reciter_id not in data.reciters:
                logger.debug('Mp3Quran: Reciter ID %d not found for URI: %s', reciter_id, uri)
                return None
            reciter = data.reciters[reciter_id]
            for moshaf in reciter['moshaf']:
                if moshaf['id'] == moshaf_id and sura_no in moshaf['surah_list']:
                    stream_url = moshaf['server'].rstrip('/') + '/%03d' % sura_no + '.mp3'
                    self.set_recently_played(
                        uri=uri, name=data.suras_name.get(sura_no, 'Surah %d' % sura_no),
                        variant='reciter', locale=locale,
                        reciter_id=reciter_id, moshaf_id=moshaf_id, sura_no=sura_no
                    )
                    if self._validate_stream_url and not self._is_url_accessible(stream_url):
                        logger.warning('Mp3Quran: Stream URL not accessible: %s', stream_url)
                        return None
                    return stream_url
            logger.debug('Mp3Quran: Moshaf %d or surah %d not found for reciter %d (URI: %s)', moshaf_id, sura_no, reciter_id, uri)
            return None
        elif variant == 'radio':
            self._init_radios(locale, data)
            if radio_id in data.radios:
                stream_url = data.radios[radio_id]['url']
                self.set_recently_played(
                    uri=uri, name=data.radios[radio_id]['name'],
                    variant='radio', locale=locale, radio_id=radio_id
                )
                if self._validate_stream_url and not self._is_url_accessible(stream_url):
                    logger.warning('Mp3Quran: Radio stream not accessible: %s', stream_url)
                    return None
                return stream_url
            logger.debug('Mp3Quran: Radio ID %d not found for URI: %s', radio_id, uri)
            return None
        elif variant == 'tafsir_audio':
            url = self.translate_tafsir_uri(tafsir_id, audio_id, locale=locale)
            if url:
                self.set_recently_played(
                    uri=uri, name='Tafsir Audio',
                    variant='tafsir_audio', locale=locale,
                    tafsir_id=tafsir_id, audio_id=audio_id
                )
                if self._validate_stream_url and not self._is_url_accessible(url):
                    logger.warning('Mp3Quran: Tafsir audio not accessible: %s', url)
                    return None
                return url
            logger.debug('Mp3Quran: Tafsir audio %d/%d not found for URI: %s', tafsir_id, audio_id, uri)
            return None

        logger.debug('Mp3Quran: Could not translate URI: %s', uri)
        return None

    def get_languages(self) -> List[Ref]:
        results = []
        for lang in self.languages:
            results.append(Ref.directory(
                uri='mp3quran:%s:language' % lang['locale'],
                name=lang['name'],
            ))
        return results

    def get_language_content(self, locale: str) -> List[Ref]:
        resolved = self.resolve_language(locale)
        results = []
        results.append(Ref.directory(uri='mp3quran:%s:reciters' % resolved, name='Reciters'))
        results.append(Ref.directory(uri='mp3quran:%s:riwayat' % resolved, name='Riwayat'))
        results.append(Ref.directory(uri='mp3quran:%s:radios' % resolved, name='Radios'))
        results.append(Ref.directory(uri='mp3quran:%s:tafasir' % resolved, name='Tafasir'))
        return results

    def get_radios(self, locale: str) -> List[Ref]:
        data = self._get_locale_data(locale)
        self._init_radios(locale, data)
        results = []
        for radio_id, radio in data.radios.items():
            results.append(Ref.track(uri='mp3quran:%s:radio:%d' % (locale, radio_id), name=radio['name']))
        return results

    def get_reciters(self, locale: str) -> List[Ref]:
        data = self._get_locale_data(locale)
        self._init_reciters(locale, data)
        results = []
        for reciter_id, reciter in data.reciters.items():
            results.append(Ref.directory(uri='mp3quran:%s:reciter:%d' % (locale, reciter_id), name=reciter['name']))
        return results

    def reciter_moshaf(self, locale: str, reciter_id: int) -> List[Ref]:
        data = self._get_locale_data(locale)
        self._init_reciters(locale, data)
        results = []
        reciter_id = int(reciter_id)
        if reciter_id not in data.reciters:
            logger.warning('Mp3Quran: Reciter ID %d not found', reciter_id)
            return results
        reciter = data.reciters[reciter_id]
        for moshaf in reciter['moshaf']:
            results.append(
                Ref.directory(
                    uri='mp3quran:%s:moshaf:%d:%d' % (locale, reciter_id, moshaf['id']),
                    name=moshaf['name'],
                )
            )
        return results

    def moshaf_suras(self, locale: str, reciter_id: int, moshaf_id: int) -> List[Ref]:
        data = self._get_locale_data(locale)
        self._init_reciters(locale, data)
        self._init_suras(locale, data)
        results = []
        reciter_id = int(reciter_id)
        moshaf_id = int(moshaf_id)
        if reciter_id not in data.reciters:
            logger.warning('Mp3Quran: Reciter ID %d not found', reciter_id)
            return results
        reciter = data.reciters[reciter_id]
        for moshaf in reciter['moshaf']:
            if moshaf['id'] == moshaf_id:
                for sura_no in moshaf['surah_list']:
                    sura_name = data.suras_name.get(sura_no, 'Surah %d' % sura_no)
                    results.append(
                        Ref.track(
                            uri='mp3quran:%s:reciter:%d:%d:%d' % (locale, reciter_id, moshaf_id, sura_no),
                            name=sura_name,
                        )
                    )
                return results
        logger.warning('Mp3Quran: Moshaf ID %d not found for reciter %d', moshaf_id, reciter_id)
        return results

    def get_riwayat(self, locale: str) -> List[Ref]:
        data = self._get_locale_data(locale)
        self._init_riwayat(locale, data)
        self._init_reciters(locale, data)
        results = []
        for riwaya_id, name in data.riwayat.items():
            reciters_with_riwaya = [
                (rid, r) for rid, r in data.reciters.items()
                if any(m['rewaya_id'] == riwaya_id for m in r['moshaf'])
            ]
            if reciters_with_riwaya:
                results.append(Ref.directory(
                    uri='mp3quran:%s:riwaya:%d' % (locale, riwaya_id), name=name,
                ))
        return results

    def riwaya_reciters(self, locale: str, riwaya_id: int) -> List[Ref]:
        data = self._get_locale_data(locale)
        self._init_riwayat(locale, data)
        self._init_reciters(locale, data)
        results = []
        riwaya_id = int(riwaya_id)
        for reciter_id, reciter in data.reciters.items():
            for moshaf in reciter['moshaf']:
                if moshaf['rewaya_id'] == riwaya_id:
                    results.append(
                        Ref.directory(
                            uri='mp3quran:%s:moshaf:%d:%d' % (locale, reciter_id, moshaf['id']),
                            name='%s - %s' % (reciter['name'], moshaf['name']),
                        )
                    )
                    break
        return results

    def get_tafasir(self, locale: str) -> List[Ref]:
        data = self._get_locale_data(locale)
        self._init_tafasir(locale, data)
        results = []
        for tafsir_id, tafsir in data.tafasir.items():
            results.append(Ref.directory(
                uri='mp3quran:%s:tafsir:%d' % (locale, tafsir_id), name=tafsir['name'],
            ))
        return results

    def tafsir_audio(self, locale: str, tafsir_id: int) -> List[Ref]:
        data = self._get_locale_data(locale)
        self._init_tafasir(locale, data)
        results = []
        tafsir_id = int(tafsir_id)
        if tafsir_id not in data.tafasir:
            logger.warning('Mp3Quran: Tafsir ID %d not found', tafsir_id)
            return results
        url = _API_BASE + 'tafsir?tafsir=%d&language=%s' % (tafsir_id, locale)
        resp = self._fetch(url)
        if resp is None:
            return results
        tafsir_data = resp.get('tafasir', {})
        for audio in tafsir_data.get('soar', []):
            try:
                results.append(Ref.track(
                    uri='mp3quran:%s:tafsir_audio:%d:%d' % (locale, tafsir_id, int(audio['id'])),
                    name=audio['name'],
                ))
            except (KeyError, ValueError) as e:
                logger.warning('Mp3Quran: Skipping invalid tafsir audio entry: %s', e)
                continue
        return results

    def translate_tafsir_uri(self, tafsir_id: int, audio_id: int, locale: str = None) -> Optional[str]:
        tafsir_id = int(tafsir_id)
        audio_id = int(audio_id)
        lang = locale or _DEFAULT_LOCALE
        data = self._get_locale_data(lang)
        self._init_tafasir(lang, data)
        if tafsir_id not in data.tafasir:
            return None
        url = _API_BASE + 'tafsir?tafsir=%d&language=%s' % (tafsir_id, lang)
        resp = self._fetch(url)
        if resp is None:
            return None
        for audio in resp.get('tafasir', {}).get('soar', []):
            try:
                if int(audio['id']) == audio_id:
                    return audio['url']
            except (KeyError, ValueError):
                logger.warning('Mp3Quran: Skipping invalid tafsir audio entry')
                continue
        return None

    def search(self, locale: str, query: str, filters: List[str] = None) -> List[Ref]:
        data = self._get_locale_data(locale)
        self._init_reciters(locale, data)
        self._init_radios(locale, data)
        self._init_riwayat(locale, data)
        self._init_tafasir(locale, data)
        self._init_suras(locale, data)

        matches = []
        filters = filters or ['reciters', 'radios', 'riwayat', 'tafasir', 'suras']
        seen_reciters = set()
        seen_riwayat = set()

        if 'reciters' in filters:
            for reciter_id, reciter in data.reciters.items():
                score = self._score_query(query, reciter['name'])
                if score >= self.fuzzy_threshold:
                    matches.append((score, Ref.directory(uri='mp3quran:%s:reciter:%d' % (locale, reciter_id), name=reciter['name'])))
                    seen_reciters.add(reciter_id)
                    continue
                for moshaf in reciter['moshaf']:
                    score = self._score_query(query, moshaf['name'])
                    if score >= self.fuzzy_threshold:
                        matches.append((score, Ref.directory(uri='mp3quran:%s:reciter:%d' % (locale, reciter_id), name=reciter['name'])))
                        seen_reciters.add(reciter_id)
                        break

        if 'radios' in filters:
            for radio_id, radio in data.radios.items():
                score = self._score_query(query, radio['name'])
                if score >= self.fuzzy_threshold:
                    matches.append((score, Ref.track(uri='mp3quran:%s:radio:%d' % (locale, radio_id), name=radio['name'])))

        if 'riwayat' in filters:
            for riwaya_id, riwaya_name in data.riwayat.items():
                if riwaya_id in seen_riwayat:
                    continue
                score = self._score_query(query, riwaya_name)
                if score >= self.fuzzy_threshold:
                    matches.append((score, Ref.directory(uri='mp3quran:%s:riwaya:%d' % (locale, riwaya_id), name=riwaya_name)))
                    seen_riwayat.add(riwaya_id)

        if 'tafasir' in filters:
            for tafsir_id, tafsir in data.tafasir.items():
                score = self._score_query(query, tafsir['name'])
                if score >= self.fuzzy_threshold:
                    matches.append((score, Ref.directory(uri='mp3quran:%s:tafsir:%d' % (locale, tafsir_id), name=tafsir['name'])))

        if 'suras' in filters:
            for sura_no, sura_name in data.suras_name.items():
                score = self._score_query(query, sura_name)
                if score >= self.fuzzy_threshold:
                    matches.append((score, Ref.track(uri='mp3quran:%s:search:sura:%d' % (locale, sura_no), name=sura_name)))

        matches.sort(key=lambda x: x[0], reverse=True)
        return [ref for _, ref in matches[:self.search_limit]]

    def refresh(self) -> None:
        self.languages = []
        self._locales.clear()
        self._languages_timestamp = 0.0
        self._init_languages()
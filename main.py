import json
import os
import sys
import time
import base64
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import requests
from bs4 import BeautifulSoup
from colorama import init, Fore, Style
from itertools import product
from binascii import Error as BinasciiError

# Initialize colorama for colored console output
init()

# Custom Exceptions
class Error(Exception):
    """Base class for other exceptions"""
    pass

class IncorrectEpisodeNumberException(Error):
    """Incorrect episode number"""
    pass

class EpisodeNumberIsOutOfRange(Error):
    """Episode number is out of range"""
    pass

class SeasonNumberIsOutOfRange(Error):
    """Season number is out of range"""
    pass

# Config Class
class Config:
    def __init__(self):
        self._load_config()
        if not self._config:
            self._prompt_initial_config()
        self._display_config()

    def _load_config(self):
        try:
            with open('config.json', 'r') as f:
                self._config = json.load(f)
        except FileNotFoundError:
            self._config = {}

    def _save_config(self):
        with open('config.json', 'w') as f:
            json.dump(self._config, f, indent=4)

    def _prompt_initial_config(self):
        print(f"{Fore.YELLOW}First-time setup. Please configure settings:{Style.RESET_ALL}")
        # Threads
        while True:
            try:
                threads = int(input(f"{Fore.YELLOW}Enter number of download threads (1-20) [default: 10]: {Style.RESET_ALL}").strip() or 10)
                if 1 <= threads <= 20:
                    break
                print(f"{Fore.RED}Please enter a number between 1 and 20{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")
        # Site URL
        print(f"{Fore.YELLOW}Select site URL:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}1 - rezka.ag (default, no login required){Style.RESET_ALL}")
        print(f"{Fore.CYAN}2 - standby-rezka.tv (requires login){Style.RESET_ALL}")
        print(f"{Fore.CYAN}3 - Custom URL (requires login){Style.RESET_ALL}")
        while True:
            choice = input(f"{Fore.YELLOW}Enter choice (1-3) [default: 1]: {Style.RESET_ALL}").strip() or "1"
            if choice in ["1", "2", "3"]:
                break
            print(f"{Fore.RED}Please select 1, 2, or 3{Style.RESET_ALL}")
        if choice == "1":
            site_url = "https://rezka.ag"
            credentials = {}
        else:
            site_url = "https://standby-rezka.tv" if choice == "2" else input(f"{Fore.YELLOW}Enter custom URL (e.g., https://example.com): {Style.RESET_ALL}").strip()
            if not site_url.startswith("https://"):
                site_url = "https://" + site_url
            print(f"{Fore.YELLOW}To find cookie parameters, visit [GitHub](https://github.com/ksardas2015/hdrezka-downloader/blob/main/docs/cookie-guide.md){Style.RESET_ALL}")
            dle_user_id = input(f"{Fore.YELLOW}Enter dle_user_id: {Style.RESET_ALL}").strip()
            dle_password = input(f"{Fore.YELLOW}Enter dle_password: {Style.RESET_ALL}").strip()
            credentials = {"dle_user_id": dle_user_id, "dle_password": dle_password}
        self._config = {
            "threads": threads,
            "site_url": site_url,
            "credentials": credentials
        }
        self._save_config()

    def _display_config(self):
        print(f"{Fore.YELLOW}Current settings:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Download threads: {self._config['threads']}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Site URL: {self._config['site_url']}{Style.RESET_ALL}")
        if self._config['credentials']:
            print(f"{Fore.CYAN}Credentials: dle_user_id={self._config['credentials']['dle_user_id']}, dle_password=*****{Style.RESET_ALL}")

    def _prompt_change_config(self):
        # Threads
        while True:
            try:
                threads_input = input(f"{Fore.YELLOW}Enter number of download threads (1-20) [current: {self._config['threads']}]: {Style.RESET_ALL}").strip()
                threads = int(threads_input) if threads_input else self._config['threads']
                if 1 <= threads <= 20:
                    break
                print(f"{Fore.RED}Please enter a number between 1 and 20{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")
        # Site URL
        print(f"{Fore.YELLOW}Select site URL [current: {self._config['site_url']}]:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}1 - rezka.ag (no login required){Style.RESET_ALL}")
        print(f"{Fore.CYAN}2 - standby-rezka.tv (requires login){Style.RESET_ALL}")
        print(f"{Fore.CYAN}3 - Custom URL (requires login){Style.RESET_ALL}")
        while True:
            choice = input(f"{Fore.YELLOW}Enter choice (1-3) [keep current: enter]: {Style.RESET_ALL}").strip()
            if choice in ["1", "2", "3", ""]:
                break
            print(f"{Fore.RED}Please select 1, 2, 3, or press enter to keep current{Style.RESET_ALL}")
        if choice:
            if choice == "1":
                site_url = "https://rezka.ag"
                credentials = {}
            else:
                site_url = "https://standby-rezka.tv" if choice == "2" else input(f"{Fore.YELLOW}Enter custom URL (e.g., https://example.com): {Style.RESET_ALL}").strip()
                if not site_url.startswith("https://"):
                    site_url = "https://" + site_url
                print(f"{Fore.YELLOW}To find cookie parameters, visit [GitHub](https://github.com/ksardas2015/hdrezka-downloader/blob/main/docs/cookie-guide.md){Style.RESET_ALL}")
                dle_user_id = input(f"{Fore.YELLOW}Enter dle_user_id [current: {self._config['credentials'].get('dle_user_id', '')}]: {Style.RESET_ALL}").strip() or self._config['credentials'].get('dle_user_id', '')
                dle_password = input(f"{Fore.YELLOW}Enter dle_password [current: *****]: {Style.RESET_ALL}").strip() or self._config['credentials'].get('dle_password', '')
                credentials = {"dle_user_id": dle_user_id, "dle_password": dle_password}
        else:
            site_url = self._config['site_url']
            credentials = self._config['credentials']
        self._config.update({
            "threads": threads,
            "site_url": site_url,
            "credentials": credentials
        })
        self._save_config()

    @property
    def config(self):
        return self._config

# Request Class
class Request:
    def __init__(self, site_url, credentials):
        self.site_url = site_url
        self.HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36'
        }
        self.COOKIES = credentials if credentials else {}

    def get(self, url, params=None, stream=False):
        return requests.get(url=url, params=params, stream=stream, headers=self.HEADERS, cookies=self.COOKIES)

    def post(self, url, data=None, params=None):
        return requests.post(url=url, data=data, params=params, headers=self.HEADERS, cookies=self.COOKIES)

# Search Class
class Search:
    def __init__(self, search_text: str, config):
        self.url = f"{config['site_url']}/search/"
        self.search_text = search_text
        self.config = config
        search_response = Request(config['site_url'], config['credentials']).get(self.url, params={'do': 'search', 'subaction': 'search', 'q': self.search_text}).content
        self.search_data = BeautifulSoup(search_response, 'html.parser')
        self.results = self.search_data.select('div.b-content__inline_item')
        self.titles_list = []
        self.__get_info()

    def __iter__(self):
        return iter(self.titles_list)

    def __str__(self):
        if not self.titles_list:
            if self.config['site_url'] == "https://rezka.ag":
                return f"{Fore.RED}No movies found, or rezka.ag is blocking your IP. Try option 2 or 3, or search again.{Style.RESET_ALL}"
            else:
                return f"{Fore.RED}No movies found. Please try searching again.{Style.RESET_ALL}"
        s = ''
        for title in self.titles_list:
            s += f"{Fore.CYAN}{title['id']} - [{title['info']['type']}] {title['name']} | Year: {title['info']['year']}{Style.RESET_ALL}\n"
        return s[:-1]

    def __get_info(self):
        for title in self.results:
            year_text = title.select_one('div.b-content__inline_item-link > div').text
            parts = year_text.split(',')
            year = parts[0].strip() if len(parts) > 0 else 'Unknown'
            country = parts[1].strip() if len(parts) > 1 else 'Unknown'
            genre = parts[2].strip() if len(parts) > 2 else 'Unknown'
            self.titles_list.append({
                'id': len(self.titles_list) + 1,
                'name': title.select_one('div.b-content__inline_item-link > a').text,
                'info': {
                    'type': title.select_one('div.b-content__inline_item-cover > a > span > i.entity').text,
                    'year': year,
                    'country': country,
                    'genre': genre
                },
                'data-id': title['data-id'],
                'url': title.select_one('div > a')['href']
            })

    def get_data(self, title_id: int):
        if title_id < 1 or title_id > len(self.titles_list):
            raise ValueError("Invalid title ID")
        return self.titles_list[title_id - 1]

# Translations Class
class Translations:
    def __init__(self, soup: BeautifulSoup):
        self.soup = soup
        self.translations = self.soup.select('ul#translators-list > li')

    def get(self):
        if self.translations:
            return [{'name': i.text, 'id': i.get('data-translator_id')} for i in self.translations]
        return None

# MovieInfo Class
class MovieInfo:
    def __init__(self, movie_data, config):
        self.data = movie_data
        self.url = movie_data['url'].split('.html')[0] + '.html'
        self.page = Request(config['site_url'], config['credentials']).get(self.url).content
        self.soup = BeautifulSoup(self.page, 'html.parser')
        self.info = None

    def __str__(self):
        s = ''
        info = self.get_data()
        if info['type'] == 'movie':
            s += f"{Fore.GREEN}Movie | {info['name']}{Style.RESET_ALL}\n"
        elif info['type'] == 'Аниме':
            s += f"{Fore.GREEN}Anime | {info['name']}{Style.RESET_ALL}\nSeasons: {info['seasons_count']}\nEpisodes: {info['seasons_episodes_count']}\nTotal Episodes: {info['allepisodes']}\n"
        else:
            s += f"{Fore.GREEN}Series | {info['name']}{Style.RESET_ALL}\nSeasons: {info['seasons_count']}\nEpisodes: {info['seasons_episodes_count']}\nTotal Episodes: {info['allepisodes']}\n"
        s += f"Year: {info['year']}\nCountry: {info['country']}\nDuration: {info['duration']}\nGenre: {', '.join(info['genre'])}\n"
        if info['translations_list']:
            s += 'Translations: ' + ', '.join([i['name'] for i in info['translations_list']]) + '\n'
        return s

    def get_data(self):
        if 'series' in self.url or 'cartoons' in self.url or 'animation' in self.url:
            return self.series_info()
        elif 'films' in self.url:
            return self.movie_info()
        else:
            return {'type': 'error', 'message': 'Wrong link!'}

    def series_info(self):
        data = {
            'type': 'series',
            'name': self.data['name'],
            'year': self.data['info']['year'],
            'allepisodes': 0,
            'country': self.data['info']['country'],
            'seasons_count': len(self.soup.select('#simple-seasons-tabs > li')),
            'rating': {'imdb': None, 'kp': None},
            'duration': self.soup.find('td', itemprop='duration').text if self.soup.find('td', itemprop='duration') else 'Unknown',
            'genre': [i.text for i in self.soup.findAll('span', itemprop='genre')],
            'translations_list': Translations(self.soup).get(),
            'data-id': self.data['data-id'],
            'url': self.url
        }
        rating = self.__get_rating()
        data.update({'rating': rating})
        episodes_count = {}
        allepisodes = 0
        for i in range(1, data['seasons_count'] + 1):
            counter = len(self.soup.select(f'#simple-episodes-list-{i} > li'))
            episodes_count[i] = counter
            allepisodes += counter
        data.update({'seasons_episodes_count': episodes_count, 'allepisodes': allepisodes})
        return data

    def movie_info(self):
        data = {
            'type': 'movie',
            'name': self.data['name'],
            'year': self.data['info']['year'],
            'country': self.data['info']['country'],
            'rating': {'imdb': None, 'kp': None},
            'duration': self.soup.find('td', itemprop='duration').text if self.soup.find('td', itemprop='duration') else 'Unknown',
            'genre': [i.text for i in self.soup.findAll('span', itemprop='genre')],
            'translations_list': Translations(self.soup).get(),
            'data-id': self.data['data-id'],
            'url': self.url
        }
        rating = self.__get_rating()
        data.update({'rating': rating})
        return data

    def __get_rating(self):
        try:
            rating_imdb = self.soup.select_one('span.b-post__info_rates.imdb > span').text
        except AttributeError:
            rating_imdb = None
        try:
            rating_kp = self.soup.select_one('span.b-post__info_rates.kp > span').text
        except AttributeError:
            rating_kp = None
        return {'imdb': rating_imdb, 'kp': rating_kp}

# GetStream Class
class GetStream:
    def __init__(self, site_url, credentials):
        self.site_url = site_url
        self.credentials = credentials

    def get_series_stream(self, data):
        t = time.time() * 1000
        params = {'t': str(t)}
        request_url = f"{self.site_url}/ajax/get_cdn_series/?t={t}"
        stream_url = ''
        decoded = False
        retries = 5
        for attempt in range(retries):
            try:
                response = Request(self.site_url, self.credentials).post(request_url, data=data, params=params)
                r = response.json()
                if r['success'] and not r['url']:
                    print(f"{Fore.RED}This content is not available in your region! Try using a VPN!{Style.RESET_ALL}")
                    sys.exit(1)
                arr = self.decode_url(r['url'], separator="//_//").split(",")
                stream_url = self.quality_select(arr, data['quality'])
                decoded = True
                break
            except (UnicodeDecodeError, BinasciiError) as e:
                print(f"{Fore.RED}Decoding error on attempt {attempt + 1}/{retries}: {e}. Retrying...{Style.RESET_ALL}")
                time.sleep(2)
            except Exception as e:
                print(f"{Fore.RED}Error fetching stream: {e}{Style.RESET_ALL}")
                break
        if not decoded:
            raise Exception("Failed to decode stream URL after multiple attempts")
        return stream_url

    def get_movie_stream(self, data):
        response = Request(self.site_url, self.credentials).get(data['url'])
        soup = BeautifulSoup(response.content, 'html.parser')
        tmp = str(soup).split('sof.tv.initCDNMoviesEvents')[-1].split('default_quality')[0]
        encoded_stream_url = tmp.split('streams')[-1][3:-3]
        stream_url = ''
        decoded = False
        retries = 5
        for attempt in range(retries):
            try:
                arr = self.decode_url(encoded_stream_url, separator="\\/\\/_\\/\\/").split(",")
                stream_url = self.quality_select(arr, data['quality'])
                decoded = True
                break
            except (UnicodeDecodeError, BinasciiError) as e:
                print(f"{Fore.RED}Decoding error on attempt {attempt + 1}/{retries}: {e}. Retrying...{Style.RESET_ALL}")
                time.sleep(2)
            except Exception as e:
                print(f"{Fore.RED}Error decoding movie stream: {e}{Style.RESET_ALL}")
                break
        if not decoded:
            raise Exception("Failed to decode movie stream URL after multiple attempts")
        return stream_url

    def get_available_qualities(self, data, is_series=True):
        try:
            if is_series:
                t = time.time() * 1000
                params = {'t': str(t)}
                request_url = f"{self.site_url}/ajax/get_cdn_series/?t={t}"
                response = Request(self.site_url, self.credentials).post(request_url, data=data, params=params)
                r = response.json()
                if r['success'] and not r['url']:
                    print(f"{Fore.RED}This content is not available in your region! Try using a VPN!{Style.RESET_ALL}")
                    return []
                arr = self.decode_url(r['url'], separator="//_//").split(",")
            else:
                response = Request(self.site_url, self.credentials).get(data['url'])
                soup = BeautifulSoup(response.content, 'html.parser')
                tmp = str(soup).split('sof.tv.initCDNMoviesEvents')[-1].split('default_quality')[0]
                encoded_stream_url = tmp.split('streams')[-1][3:-3]
                arr = self.decode_url(encoded_stream_url, separator="\\/\\/_\\/\\/").split(",")
            resolutions = []
            for item in arr:
                if "]" in item and " or " in item:
                    resolution, _ = item.split("]")
                    if item.endswith(".mp4"):
                        resolutions.append(resolution + "]")
            return resolutions
        except Exception as e:
            print(f"{Fore.RED}Error fetching available qualities: {e}{Style.RESET_ALL}")
            return []

    @staticmethod
    def quality_select(stream_list, quality):
        resolutions_and_urls = []
        for item in stream_list:
            if "]" in item and " or " in item:
                resolution, url = item.split("]")
                if url.endswith(".mp4"):
                    resolutions_and_urls.append((resolution + "]", url.split(" or ")[-1]))
        if not resolutions_and_urls:
            raise ValueError("No valid streams found")
        selected_index = -1
        for index, item in enumerate(resolutions_and_urls):
            if quality in item[0]:
                selected_index = index
                break
        if selected_index == -1:
            print(f"{Fore.YELLOW}Requested quality {quality} not found, defaulting to highest available{Style.RESET_ALL}")
            selected_index = -1
        stream_url = resolutions_and_urls[selected_index][1]
        print(f"{Fore.GREEN}Selected quality: {resolutions_and_urls[selected_index][0]}{Style.RESET_ALL}")
        return stream_url

    @staticmethod
    def decode_url(data, separator):
        trash_list = ["@", "#", "!", "^", "$"]
        trash_codes_set = []
        for i in range(2, 4):
            startchar = ''
            for chars in product(trash_list, repeat=i):
                data_bytes = startchar.join(chars).encode("utf-8")
                trashcombo = base64.b64encode(data_bytes)
                trash_codes_set.append(trashcombo)
        arr = data.replace("#h", "").split(separator)
        trash_string = ''.join(arr)
        for i in trash_codes_set:
            temp = i.decode("utf-8")
            trash_string = trash_string.replace(temp, '')
        final_string = base64.b64decode(trash_string + "==")
        return final_string.decode("utf-8")

# Download Class
class Download:
    def __init__(self, download_data, quality, config):
        self.data = download_data
        self.quality = quality
        self.url = download_data['url']
        self.name = download_data['url'].split('/')[-1].split('.')[0]
        self.config = config
        self.translator_id = self.__get_translation() if download_data['translations_list'] else self.__detect_translation()

    def download_movie(self):
        if self.__is_movie_downloaded(check_size=True):
            print(f"{Fore.GREEN}Movie {self.name} already downloaded and verified{Style.RESET_ALL}")
            return
        data = {
            'id': self.data['data-id'],
            'translator_id': self.translator_id,
            'action': 'get_movie',
            'quality': self.quality,
            'url': self.url
        }
        try:
            stream_url = GetStream(self.config['site_url'], self.config['credentials']).get_movie_stream(data)
            if ".mp4" in stream_url:
                stream_url = stream_url.split(".mp4")[0] + ".mp4"
            downloaded_folder = os.path.join("downloads", self.name)
            os.makedirs(downloaded_folder, exist_ok=True)
            file_name = f"{downloaded_folder}/{self.name}-{self.quality}.mp4"
            self.__download({'stream_url': stream_url, 'file_name': file_name})
        except Exception as e:
            print(f"{Fore.RED}Failed to download movie: {e}{Style.RESET_ALL}")

    def download_all_serial(self):
        print(f"{Fore.YELLOW}Downloading entire series: {self.name}{Style.RESET_ALL}")
        for season in range(1, self.data['seasons_count'] + 1):
            self.download_season(season)

    def download_season(self, season):
        if season < 1 or season > self.data['seasons_count']:
            raise SeasonNumberIsOutOfRange(f"Season {season} is out of range (1-{self.data['seasons_count']}).")
        episodes_count = self.data['seasons_episodes_count'][season]
        print(f"{Fore.YELLOW}Downloading Season {season} ({episodes_count} episodes){Style.RESET_ALL}")
        with ThreadPoolExecutor(max_workers=self.config['threads']) as executor:
            futures = [executor.submit(self.__download_with_retries, season, episode) for episode in range(1, episodes_count + 1)]
            for future in futures:
                future.result()

    def download_episodes(self, season, start_episode, end_episode):
        if season < 1 or season > self.data['seasons_count']:
            raise SeasonNumberIsOutOfRange(f"Season {season} is out of range (1-{self.data['seasons_count']}).")
        episodes_count = self.data['seasons_episodes_count'][season]
        if start_episode < 1 or end_episode > episodes_count or start_episode > end_episode:
            raise EpisodeNumberIsOutOfRange(f"Episode range {start_episode}-{end_episode} is out of range (1-{episodes_count}).")
        print(f"{Fore.YELLOW}Downloading episodes from S{season:02}E{start_episode:02} to S{season:02}E{end_episode:02}{Style.RESET_ALL}")
        with ThreadPoolExecutor(max_workers=self.config['threads']) as executor:
            futures = [executor.submit(self.__download_with_retries, season, episode) for episode in range(start_episode, end_episode + 1)]
            for future in futures:
                future.result()

    def download_seasons(self, start, end):
        if start < 1 or end > self.data['seasons_count'] or start > end:
            raise SeasonNumberIsOutOfRange(f"Season range {start}-{end} is invalid.")
        for season in range(start, end + 1):
            self.download_season(season)

    def __download_with_retries(self, season, episode, retries=5, delay=10):
        if self.__is_episode_downloaded(season, episode, check_size=True):
            print(f"{Fore.GREEN}S{season:02}E{episode:02} already downloaded and verified{Style.RESET_ALL}")
            return
        for attempt in range(retries):
            try:
                self.download_episode(season, episode)
                if self.__is_episode_downloaded(season, episode, check_size=True):
                    print(f"{Fore.GREEN}S{season:02}E{episode:02} downloaded successfully{Style.RESET_ALL}")
                    return
                else:
                    print(f"{Fore.YELLOW}S{season:02}E{episode:02} downloaded but verification failed. Retrying...{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Error downloading S{season:02}E{episode:02}: {e}{Style.RESET_ALL}")
                if attempt < retries - 1:
                    print(f"{Fore.YELLOW}Retrying in {delay} seconds...{Style.RESET_ALL}")
                    time.sleep(delay)
                else:
                    print(f"{Fore.RED}Failed to download S{season:02}E{episode:02} after {retries} attempts{Style.RESET_ALL}")

    def download_episode(self, season, episode):
        if season > self.data['seasons_count'] or episode < 1 or episode > self.data['seasons_episodes_count'][season]:
            raise IncorrectEpisodeNumberException(f"Invalid episode S{season:02}E{episode:02}")
        data = {
            'id': self.data['data-id'],
            'translator_id': self.translator_id,
            'season': season,
            'episode': episode,
            'action': 'get_stream',
            'quality': self.quality
        }
        stream_url = GetStream(self.config['site_url'], self.config['credentials']).get_series_stream(data)
        if ".mp4" in stream_url:
            stream_url = stream_url.split(".mp4")[0] + ".mp4"
        downloaded_folder = os.path.join("downloads", self.name)
        os.makedirs(downloaded_folder, exist_ok=True)
        season_str = str(season).zfill(2)
        episode_str = str(episode).zfill(2)
        file_name = f"{downloaded_folder}/s{season_str}e{episode_str}-{self.quality}.mp4"
        self.__download({'stream_url': stream_url, 'file_name': file_name})

    @staticmethod
    def __download(download_data):
        file_name = download_data['file_name']
        stream_url = download_data['stream_url']
        print(f"{Fore.CYAN}Downloading: {file_name}{Style.RESET_ALL}")
        fullpath = os.path.join(os.path.curdir, file_name)
        try:
            with Request(download_data.get('site_url', 'https://rezka.ag'), download_data.get('credentials', {})).get(stream_url, stream=True) as r, open(fullpath, "wb") as f, tqdm(
                unit="B", unit_scale=True, unit_divisor=1024, total=int(r.headers.get('content-length', 0)),
                file=sys.stdout, desc=os.path.basename(file_name), bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]"
            ) as progress:
                for chunk in r.iter_content(chunk_size=1024 * 4):
                    if chunk:
                        f.write(chunk)
                        progress.update(len(chunk))
        except Exception as e:
            print(f"{Fore.RED}Download failed for {file_name}: {e}{Style.RESET_ALL}")
            if os.path.exists(fullpath):
                os.remove(fullpath)  # Remove incomplete file
            raise

    def __get_translation(self) -> int:
        print(f"{Fore.YELLOW}Available translations:{Style.RESET_ALL}")
        for i, translation in enumerate(self.data['translations_list'], start=1):
            print(f"{Fore.CYAN}{i} - {translation['name']}{Style.RESET_ALL}")
        while True:
            try:
                choice = int(input(f"{Fore.YELLOW}Enter translation number: {Style.RESET_ALL}"))
                if 1 <= choice <= len(self.data['translations_list']):
                    return self.data['translations_list'][choice - 1]['id']
                print(f"{Fore.RED}Invalid choice. Please select a number between 1 and {len(self.data['translations_list'])}{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")

    def __detect_translation(self) -> int:
        print(f"{Fore.YELLOW}No translations available, using default translator ID{Style.RESET_ALL}")
        return 0  # Default translator ID

    def __is_episode_downloaded(self, season, episode, check_size=False):
        season_str = str(season).zfill(2)
        episode_str = str(episode).zfill(2)
        # Use absolute path to avoid relative path issues
        file_name = os.path.join(os.getcwd(), "downloads", self.name, f"s{season_str}e{episode_str}-{self.quality}.mp4")
        if not os.path.isfile(file_name):
            return False
        if check_size:
            try:
                data = {
                    'id': self.data['data-id'],
                    'translator_id': self.translator_id,
                    'season': season,
                    'episode': episode,
                    'action': 'get_stream',
                    'quality': self.quality
                }
                stream_url = GetStream(self.config['site_url'], self.config['credentials']).get_series_stream(data)
                if ".mp4" in stream_url:
                    stream_url = stream_url.split(".mp4")[0] + ".mp4"
                with Request(self.config['site_url'], self.config['credentials']).get(stream_url, stream=True) as r:
                    expected_size = int(r.headers.get('content-length', 0))
                actual_size = os.path.getsize(file_name)
                # Allow 10% margin for size comparison to account for metadata differences
                if expected_size == 0 or actual_size >= expected_size * 0.9:
                    return True
                else:
                    print(f"{Fore.YELLOW}File S{season_str}E{episode_str} exists but size mismatch (actual: {actual_size}, expected: {expected_size}). Redownloading.{Style.RESET_ALL}")
                    os.remove(file_name)  # Remove incomplete file
                    return False
            except Exception as e:
                print(f"{Fore.YELLOW}Size check failed for S{season_str}E{episode_str}: {e}. Assuming incomplete.{Style.RESET_ALL}")
                os.remove(file_name) if os.path.exists(file_name) else None  # Remove potentially corrupt file
                return False
        return True

    def __is_movie_downloaded(self, check_size=False):
        file_name = os.path.join(os.getcwd(), "downloads", self.name, f"{self.name}-{self.quality}.mp4")
        if not os.path.isfile(file_name):
            return False
        if check_size:
            try:
                data = {
                    'id': self.data['data-id'],
                    'translator_id': self.translator_id,
                    'action': 'get_movie',
                    'quality': self.quality,
                    'url': self.url
                }
                stream_url = GetStream(self.config['site_url'], self.config['credentials']).get_movie_stream(data)
                if ".mp4" in stream_url:
                    stream_url = stream_url.split(".mp4")[0] + ".mp4"
                with Request(self.config['site_url'], self.config['credentials']).get(stream_url, stream=True) as r:
                    expected_size = int(r.headers.get('content-length', 0))
                actual_size = os.path.getsize(file_name)
                # Allow 10% margin for size comparison
                if expected_size == 0 or actual_size >= expected_size * 0.9:
                    return True
                else:
                    print(f"{Fore.YELLOW}File {self.name} exists but size mismatch (actual: {actual_size}, expected: {expected_size}). Redownloading.{Style.RESET_ALL}")
                    os.remove(file_name)  # Remove incomplete file
                    return False
            except Exception as e:
                print(f"{Fore.YELLOW}Size check failed for {self.name}: {e}. Assuming incomplete.{Style.RESET_ALL}")
                os.remove(file_name) if os.path.exists(file_name) else None  # Remove potentially corrupt file
                return False
        return True

# Main Function
def main():
    config = Config()
    while True:
        search_input = input(f"{Fore.YELLOW}Enter title to search or '1' to change settings: {Style.RESET_ALL}").strip()
        if search_input == "1":
            config._prompt_change_config()
            config._display_config()
            continue
        if search_input:
            search_text = search_input
            search_result = Search(search_text, config.config)
            print(search_result)
            if not search_result.titles_list:
                continue  # Return to search prompt if no results
            while True:
                try:
                    title_id = int(input(f"{Fore.YELLOW}Enter title number: {Style.RESET_ALL}"))
                    movie_data = search_result.get_data(title_id)
                    break
                except ValueError:
                    print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")
                except IndexError:
                    print(f"{Fore.RED}Invalid title ID{Style.RESET_ALL}")
            break
        print(f"{Fore.RED}Please enter a title or '1' to change settings{Style.RESET_ALL}")

    movie_info = MovieInfo(movie_data, config.config)
    print(movie_info)
    download_data = movie_info.get_data()
    if download_data.get('type') == 'error':
        print(f"{Fore.RED}Error: {download_data['message']}{Style.RESET_ALL}")
        return

    # Fetch available qualities
    get_stream = GetStream(config.config['site_url'], config.config['credentials'])
    is_series = download_data['type'] != 'movie'
    data = {
        'id': download_data['data-id'],
        'translator_id': download_data['translations_list'][0]['id'] if download_data['translations_list'] else 0,
        'season': 1 if is_series else None,
        'episode': 1 if is_series else None,
        'action': 'get_stream' if is_series else 'get_movie',
        'quality': '1080p',  # Default quality for probing
        'url': download_data['url']
    }
    available_qualities = get_stream.get_available_qualities(data, is_series)
    if not available_qualities:
        print(f"{Fore.RED}No qualities available for this media. Exiting.{Style.RESET_ALL}")
        return

    print(f"{Fore.YELLOW}Available qualities:{Style.RESET_ALL}")
    for i, quality in enumerate(available_qualities, 1):
        print(f"{Fore.CYAN}{i} - {quality}{Style.RESET_ALL}")
    while True:
        try:
            choice = int(input(f"{Fore.YELLOW}Select quality number: {Style.RESET_ALL}"))
            if 1 <= choice <= len(available_qualities):
                quality = available_qualities[choice - 1].strip('[]')  # Remove brackets
                break
            print(f"{Fore.RED}Invalid choice. Please select a number between 1 and {len(available_qualities)}{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")

    downloader = Download(download_data, quality, config.config)

    if download_data['type'] == 'movie':
        downloader.download_movie()
        print(f"{Fore.GREEN}Movie download completed!{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}Download options:{Style.RESET_ALL}")
        print("1 - Download a single season")
        print("2 - Download specific episodes")
        print("3 - Download a range of seasons")
        print("4 - Download entire series")
        while True:
            try:
                download_type = int(input(f"{Fore.YELLOW}Select download type: {Style.RESET_ALL}"))
                if download_type in [1, 2, 3, 4]:
                    break
                print(f"{Fore.RED}Please select a valid option (1-4){Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")

        if download_type == 1:
            while True:
                try:
                    season = int(input(f"{Fore.YELLOW}Enter season number: {Style.RESET_ALL}"))
                    if 1 <= season <= download_data['seasons_count']:
                        downloader.download_season(season)
                        break
                    print(f"{Fore.RED}Invalid season. Choose between 1 and {download_data['seasons_count']}{Style.RESET_ALL}")
                except ValueError:
                    print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")
            print(f"{Fore.GREEN}Season {season} download completed!{Style.RESET_ALL}")
        elif download_type == 2:
            while True:
                try:
                    season = int(input(f"{Fore.YELLOW}Enter season number: {Style.RESET_ALL}"))
                    if 1 <= season <= download_data['seasons_count']:
                        break
                    print(f"{Fore.RED}Invalid season. Choose between 1 and {download_data['seasons_count']}{Style.RESET_ALL}")
                except ValueError:
                    print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")
            episodes_count = download_data['seasons_episodes_count'][season]
            print(f"{Fore.CYAN}Season {season} has {episodes_count} episodes{Style.RESET_ALL}")
            while True:
                try:
                    start = int(input(f"{Fore.YELLOW}Enter starting episode: {Style.RESET_ALL}"))
                    end = int(input(f"{Fore.YELLOW}Enter ending episode: {Style.RESET_ALL}"))
                    if 1 <= start <= end <= episodes_count:
                        downloader.download_episodes(season, start, end)
                        break
                    print(f"{Fore.RED}Invalid episode range. Choose between 1 and {episodes_count}{Style.RESET_ALL}")
                except ValueError:
                    print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")
            print(f"{Fore.GREEN}Episodes download completed!{Style.RESET_ALL}")
        elif download_type == 3:
            while True:
                try:
                    start = int(input(f"{Fore.YELLOW}Enter start season: {Style.RESET_ALL}"))
                    end = int(input(f"{Fore.YELLOW}Enter end season: {Style.RESET_ALL}"))
                    if 1 <= start <= end <= download_data['seasons_count']:
                        downloader.download_seasons(start, end)
                        break
                    print(f"{Fore.RED}Invalid season range. Choose between 1 and {download_data['seasons_count']}{Style.RESET_ALL}")
                except ValueError:
                    print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")
            print(f"{Fore.GREEN}Seasons download completed!{Style.RESET_ALL}")
        elif download_type == 4:
            downloader.download_all_serial()
            print(f"{Fore.GREEN}Series download completed!{Style.RESET_ALL}")

if __name__ == "__main__":
    main()

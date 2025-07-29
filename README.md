
# HDRezka Downloader

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)

**HDRezka Downloader** is a Python script for searching and downloading movies and series from [rezka.ag](https://rezka.ag), [standby-rezka.tv](https://standby-rezka.tv), or custom URLs. It supports multi-threaded downloads, quality selection, and episode/season range downloads with a user-friendly CLI interface.

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Getting Cookies for Login](#getting-cookies-for-login)
- [Contributing](#contributing)
- [License](#license)
- [Support](#support)

---

## Features

- **Search**: Find movies, series, or anime by title on supported sites.
- **Download Options**:
  - Movies in selected quality (e.g., 360p, 720p, 1080p).
  - Series by season, episode range, or entire series.
- **Multi-threading**: Download multiple episodes simultaneously (configurable threads).
- **Quality Selection**: Choose from available video qualities.
- **File Verification**: Skips completed downloads with size validation (95% margin).
- **Supported Sites**:
  - [rezka.ag](https://rezka.ag) (no login required).
  - [standby-rezka.tv](https://standby-rezka.tv) or custom URLs (requires `dle_user_id` and `dle_password` cookies).

---

## Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/ksardas2015/hdrezka-downloader.git
   cd hdrezka-downloader
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Ensure Python 3.8+**:
   ```bash
   python --version
   ```

---

## Usage

1. **Run the Script**:
   ```bash
   python main.py
   ```

2. **Follow Prompts**:
   - **Initial Setup** (first run):
     - Set number of download threads (1-20, default: 10).
     - Choose site: `rezka.ag`, `standby-rezka.tv`, or custom URL.
     - For `standby-rezka.tv` or custom URLs, provide `dle_user_id` and `dle_password` (see [Getting Cookies for Login](#getting-cookies-for-login)).
   - **Search**: Enter a movie/series title or `1` to change settings.
   - **Select Title**: Choose from search results by number.
   - **Choose Quality**: Select from available qualities (e.g., 1080p).
   - **For Series**:
     - Choose translation (if available).
     - Select download type: single season, episode range, season range, or entire series.
   - **Output**: Files are saved in `../{title}/` as `{title}-{quality}.mp4` (movies) or `s{season}e{episode}-{quality}.mp4` (series).

**Example**:
```bash
$ python main.py
Current settings:
Download threads: 10
Site URL: https://rezka.ag
Credentials: None
Enter title to search or '1' to change settings: prison break
1 - [Series] Prison Break | Year: 2005-2009
2 - [Movie] Prison Break: The Final Break | Year: 2009
Enter title number: 1
Series | Prison Break
Seasons: 4
Episodes: {1: 22, 2: 22, 3: 13, 4: 21}
...
```

---

## Configuration

Settings are stored in `config.json`:

- **threads**: Number of concurrent download threads (1-20).
- **site_url**: Target site (`https://rezka.ag`, `https://standby-rezka.tv`, or custom).
- **credentials**: `dle_user_id` and `dle_password` for sites requiring login.

**Example `config.json`**:
```json
{
    "threads": 10,
    "site_url": "https://rezka.ag",
    "credentials": {}
}
```

To change settings, enter `1` at the search prompt.

---

## Getting Cookies for Login

For `standby-rezka.tv` or custom URLs, you need `dle_user_id` and `dle_password` cookies. Follow the [Cookie Retrieval Guide](docs/cookie-guide.md) to obtain them.


⭐ **Star this repo if you find it useful!** ⭐
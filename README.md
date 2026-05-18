# Discord Humanizer

A Discord account humanizer tool made for bulk profile customization.

## Features

- Random display names
- Random bios
- Random pronouns
- Avatar changer
- HypeSquad changer
- Proxy support
- Multi-threaded processing
- Auto retry system
- Token success/failed sorting
- Dynamic Discord build fetch
- Clean console logs

---

# Setup

## Install Python

Download Python 3.11+ from:

https://www.python.org/downloads/

Make sure to enable:

- Add Python to PATH

---

# Installation

Open terminal inside the project folder and run:

```bash
pip install -r req.txt
```

Or just run:

```bash
python main.py
```

Missing packages will install automatically.

---

# Folder Structure

```text
data/
├── bios.txt
├── names.txt
└── pronouns.txt

input/
├── tokens.txt
├── proxies.txt
├── success.txt
└── failed.txt

avatar/
├── avatar1.png
├── avatar2.jpg
└── etc...
```

---

# Input Files

## tokens.txt

Put 1 token per line.

Example:

```text
token_here
token_here
```

---

## proxies.txt

Supported formats:

```text
ip:port
ip:port:user:pass
user:pass@ip:port
http://user:pass@ip:port
```

Leave empty if you do not want proxies.

---

## names.txt

Example:

```text
zenkai
akira
ghost
```

---

## bios.txt

Example:

```text
sleeping
touching grass
idk anymore
```

---

## pronouns.txt

Example:

```text
he/him
she/her
they/them
```

---

# Config

Edit `config.json`

Example:

```json
{
  "max_threads": 3,
  "avatar_dimension": 256,
  "max_avatar_cache": 100,
  "update_display_name": true,
  "update_bio": true,
  "update_pronouns": true,
  "update_avatar": true,
  "update_hypesquad": true,
  "RetryLimit": 1
}
```

---

# Running

```bash
python main.py
```

You will be asked for thread count when starting.

---

# Results

Successful tokens:

```text
input/success.txt
```

Failed tokens:

```text
input/failed.txt
```

Processed tokens are removed automatically from `tokens.txt`.

---

# Notes

- Use good quality proxies for better success rates
- PNG/JPG/GIF/WebP avatars supported
- Bad proxies are removed automatically
- Large avatars are compressed automatically
- Duplicate tokens are ignored

---

# Requirements

- Python 3.11+
- Windows recommended

---

# Credits

Developer: zenkai
```

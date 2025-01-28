# Job Ads Scrape

This scrapes the CSJ job site, with certain search options. It saves the resulting jobs:

* basic data is added to [Job Ads - Google Sheet](https://docs.google.com/spreadsheets/d/1Ugt9kMQq-S8q1fm3u8RNKjNb2-fwiXDhf4ooFirGIRs/edit?gid=0#gid=0)
* job PDF is saved to [this repo's jobs folder](https://github.com/davidread/jobadscrape/tree/main/jobs)

## Setup

```sh
python3 -m venv venv
. venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# weasyprint dependencies
brew install cairo pango gobject-introspection
```

If you get error `OSError: cannot load library 'libgobject-2.0-0'` then add to your shell (e.g. `.zshrc`):
```sh
# library paths
export LIBRARY_PATH="/opt/homebrew/lib:$LIBRARY_PATH"
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"
```
and reload it:
```sh
source ~/.zshrc
```

For uploading results to the Google Sheets, setup and download the Google Service Account token, that has permission to write to the sheet:

* Go to Google Cloud Console
* Create a new project
* Enable the Google Sheets API
* Create a service account
* Download the service account key JSON file as `job-scraper-service-account-key.json`
* In the Sheet, share it with the service account's email address

For saving PDF files to GitHub, generate a [personal access token](https://github.com/settings/tokens) and export the value:

```sh
export GITHUB_TOKEN=...
```

## Run

```
. venv/bin/activate
export GITHUB_TOKEN=...
python3 scrape.py
```

import argparse
import asyncio
from base64 import b64encode
from collections import defaultdict
from datetime import datetime
from enum import Enum, auto
import json
import os
from pprint import pprint
import re
import sys
import time
from urllib.parse import urljoin, urlparse

from altcha import solve_altcha
from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import requests
from weasyprint import HTML

# Scrape
SEARCH_OPTIONS_LIST = [
    {
        "department": "256999", # "Government Digital Service"
        "output folder": "gds",
    }, 
    {
        "department": "258439", # "Central Digital and Data Office"
        "output folder": "cddo",
    },
    {
        "department": "183940", # "Ministry of Justice"
        "type of role": "249407", # digital
        "output folder": "moj",
    },
    {
        "what": "developer",
        "what_exact_match": "developer",  # to avoid matching on "development"
        "output folder": "developer",
    },
    {
        "what": "software engineer",
        "output folder": "developer",
    },
    {
        "what": "technical architect",
        "what_exact_match": "architect",  # to avoid matching on body text
        "output folder": "technical-architect",
    },
    {
        "what": "technologist",
        "output folder": "technologist",
    },
]
BASE_URL = "https://www.civilservicejobs.service.gov.uk"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0"
}

# Data saved to Google Sheets
# https://docs.google.com/spreadsheets/d/1Ugt9kMQq-S8q1fm3u8RNKjNb2-fwiXDhf4ooFirGIRs/edit?usp=sharing
SPREADSHEET_ID = '1Ugt9kMQq-S8q1fm3u8RNKjNb2-fwiXDhf4ooFirGIRs'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
RANGE_NAME = 'Sheet1!A:Z' 

# PDFs saved to Github
REPO_OWNER = "davidread"
REPO_NAME = "jobadscrape"
REPO_BRANCH = "main"

class ScrapeResult(Enum):
    NEW = auto()
    EXISTING = auto()
    ERROR = auto()

class ScrapingStats:
    def __init__(self):
        self.stats = defaultdict(lambda: {result: 0 for result in ScrapeResult})
        self.errored = False
        
    def add_job(self, id_, result):
        self.stats[id_][result] += 1
        if result == ScrapeResult.ERROR:
            self.errored = True
    
    def print_summary(self):
        print("\n=== Scraping Summary ===")
        total_by_result = defaultdict(int)
        
        for id_, counts in self.stats.items():
            total = sum(counts.values())
            
            print(f"\n{id_}:")
            print(f"  Total jobs found: {total}")
            print(f"  New jobs uploaded: {counts[ScrapeResult.NEW]} ({(counts[ScrapeResult.NEW]/total * 100):.1f}%)")
            print(f"  Existing jobs: {counts[ScrapeResult.EXISTING]}")
            if counts[ScrapeResult.ERROR]:
                print(f"  ERRORS: {counts[ScrapeResult.ERROR]} ({(counts[ScrapeResult.ERROR]/total * 100):.1f}%)")
            
            for result, count in counts.items():
                total_by_result[result] += count
        
        total_jobs = sum(total_by_result.values())
        print("\nOverall Summary:")
        print(f"  Total jobs found: {total_jobs}")
        print(f"  New jobs uploaded: {total_by_result[ScrapeResult.NEW]} ({(total_by_result[ScrapeResult.NEW]/total_jobs * 100):.1f}%)")
        print(f"  Existing jobs: {total_by_result[ScrapeResult.EXISTING]}")
        errors = total_by_result[ScrapeResult.ERROR]
        if errors:
            print(f"  ERRORS: {errors} ({(errors/total_jobs * 100):.1f}%)")
        print("=====================")

def solve_captcha():
    """Solve the ALTCHA captcha and transfer cookies to the requests session."""
    print("Solving ALTCHA captcha...")
    captcha_url = f"{BASE_URL}/csr/index.cgi"
    cookies = asyncio.run(solve_altcha(captcha_url, headless=True))
    for cookie in cookies:
        requests_session.cookies.set(
            cookie['name'], cookie['value'],
            domain=cookie.get('domain', ''),
            path=cookie.get('path', '/'),
        )
    print(f"ALTCHA solved, {len(cookies)} cookies transferred to session")

def scrape_jobs(search_options_list, dry_run):
    print("Starting job scraping...\n")
    stats = ScrapingStats()

    # Fetch a list of PDFs already in GitHub
    github_token = get_github_token()
    file_list = fetch_all_files_from_github(github_token) if github_token else []

    # Initialize Google Sheets service
    jobs_google_sheet = JobsGoogleSheet()
    if not jobs_google_sheet:
        print("Warning: Google Sheets service not initialized. Will continue without saving to sheets.")
    else:
        print(f"Found {jobs_google_sheet.num_jobs} existing jobs in sheet")

    solve_captcha()
    sid = get_fresh_sid()
    reqsig = get_reqsig(sid)

    for search_options in search_options_list:
        output_folder = f'jobs/{search_options.pop("output folder")}'
        os.makedirs(output_folder, exist_ok=True)
        
        # Perform search
        search_url = f"{BASE_URL}/csr/esearch.cgi"
        params = {"SID": sid}
        payload = {
            "reqsig": reqsig,
            "SID": sid,
            # "what": None,
            # "where": None,
            # "id_postcodeselectorid": "#where",
            # "distance": 10,
            # "units": "miles",
            # "overseas": 1,
            # "oselect-filter-textbox": None,
            # "oselect-filter-textbox": None,
            # "salaryminimum": "NULL",
            # "salarymaximum": "NULL",
            # "oselect-filter-textbox": None,
            # "oselect-filter-textbox": None,
            # "oselect-filter-textbox": None,
            # "update_button": "Update results",
            # "csource": "csfsearch",
            # "easting": None,
            # "northing": None,
            # "region": None,
            # "id_chosen_placeholder_text_multiple": "resultpage",
            # "whatoption": "words",
            }
        if "department" in search_options:
            payload["nghr_dept"] = search_options.pop("department")
        if "type of role" in search_options:
            payload["nghr_job_category"] = search_options.pop("type of role")
        if "what" in search_options:
            payload["what"] = search_options.pop("what")
        if "what_exact_match" in search_options:
            what_exact_match = search_options.pop("what_exact_match")
        else:
            what_exact_match = None
        assert not search_options, f"Unprocessed options {search_options}"
        filtered_payload = {k: v for k, v in payload.items() if k not in ['reqsig', 'SID']}
        print(f"\nSearch: {filtered_payload}")

        # Page through results
        current_url = search_url
        page_number = 1

        while True:            
            if page_number == 1:
                # First page uses POST with payload
                response = requests_session.post(current_url, data=payload, headers=HEADERS)
            else:
                # Subsequent pages use GET with the full URL
                print(f"\nProcessing page {page_number}")
                response = requests_session.get(current_url, headers=HEADERS)
            response.raise_for_status()
            
            # Parse search results
            soup = BeautifulSoup(response.text, "html.parser")
            job_results = soup.find_all("li", class_="search-results-job-box")
            print(f"Found {len(job_results)} job listings on page {page_number}")

            for job_result in job_results:
                try:
                    # Extract info from search result
                    job_data = scrape_job_search_result(job_result)
                    if job_data is None:
                        continue
                    
                    if what_exact_match and what_exact_match.lower() not in job_data['title'].lower():
                        # Require an exact match in the job title.
                        # The reason is that CSJ's search is very broad:
                        # e.g. "Intelligence Development Officer" job matches "Developer", probably due to stemming
                        # e.g. "User Researcher" job matches "Technical Architect", when the latter is mentioned as a colleague in the job description
                        print(f'Ignoring job "{job_data["title"]}" as it is not an exact match of "{what_exact_match}"')
                        continue

                    # Check if job already exists in the sheet
                    row_in_sheet = jobs_google_sheet.get_job_row(job_data)
                    if row_in_sheet is not None:
                        print(f"Job already exists in sheet - row {row_in_sheet}")
                        stats.add_job(output_folder, ScrapeResult.EXISTING)
                        continue
                    
                    # Add to sheet
                    if jobs_google_sheet and jobs_google_sheet.append_to_sheets(job_data, dry_run):
                        # If successfully added to sheet, fetch full page and save PDF
                        if scrape_job_page(job_data, output_folder, file_list, jobs_google_sheet, dry_run):
                            stats.add_job(output_folder, ScrapeResult.NEW)
                        else:
                            stats.add_job(output_folder, ScrapeResult.ERROR)
                    else:
                        stats.add_job(output_folder, ScrapeResult.ERROR)
                        
                except Exception as e:
                    print(f"Error processing job box: {e}")
                    stats.add_job(output_folder, ScrapeResult.ERROR)

            # Check for next page
            next_url = get_next_page_url(soup, BASE_URL)
            if not next_url:
                print(f"No more pages to process")
                break
                
            current_url = next_url
            page_number += 1

    # Print summary at the end
    stats.print_summary()
    return stats

def get_fresh_sid():
    """Fetch a fresh SID from the website."""
    initial_url = f"{BASE_URL}/csr/index.cgi"
    response = requests_session.get(initial_url, headers=HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    
    # Option 1: Extract SID from a hidden input field (most common case)
    sid_input = soup.find("input", {"name": "SID"})
    if sid_input:
        # print("SID from input field")
        return sid_input["value"]

    # Option 2: Extract SID from the URL in the "action" or "form" element
    form_action = soup.find("form")["action"]
    if "SID=" in form_action:
        # print("SID from form URL")
        return form_action.split("SID=")[1].split("&")[0]
    
def get_reqsig(sid):
    url = f"{BASE_URL}/csr/esearch.cgi?SID="
    params = {"SID": sid}
    response = requests_session.get(url, params=params, headers=HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    return extract_reqsig(soup)

def extract_reqsig(soup):
    reqsig_input = soup.find("input", {"name": "reqsig"})
    assert reqsig_input
    reqsig = reqsig_input["value"]
    return reqsig

def get_next_page_url(soup, base_url):
    """Extract the next page URL from the pagination section"""
    pagination = soup.find_all("div", class_="search-results-paging-menu")
    if not pagination:
        return None
        
    # Look for the "next »" link
    next_link = pagination[-1].find('a', string=lambda t: t and '»' in t)
    if next_link:
        return ensure_absolute_url(next_link['href'], base_url)
    return None

def ensure_absolute_url(href, base_url):
    if not bool(urlparse(href).scheme):
        # href is a relative link
        return urljoin(base_url, href)
    return href

def scrape_job_search_result(job_box):
    """Extract job information from a search result box."""
    if job_box.attrs.get("title") == "Your search matched no jobs":
        return

    # Extract basic info
    title_tag = job_box.find("h3", class_="search-results-job-box-title")
    job_title = title_tag.get_text(strip=True)
    job_link = title_tag.find("a")["href"]
    department = job_box.find("div", class_="search-results-job-box-department").get_text(strip=True)
    
    # Extract salary
    salary_elem = job_box.find("div", class_="search-results-job-box-salary")
    salary_min, salary_max = extract_salary_range(salary_elem) if salary_elem else (None, None)
    
    # Extract location
    location_elem = job_box.find("div", class_="search-results-job-box-location")
    location = location_elem.get_text(strip=True) if location_elem else None
    
    # Extract reference
    ref_elem = job_box.find("div", class_="search-results-job-box-refcode")
    reference = extract_reference(ref_elem) if ref_elem else None
    reference = None
    if ref_elem:
        ref_text = ref_elem.get_text(strip=True)
        match = re.search(r'(?:Reference|Ref|Reference number)\s?:\s*([^\s]+)', ref_text, re.IGNORECASE)
        reference = match.group(1) if match else ref_text
    
    # Extract closing date
    closing_date = None
    closing_date_elem = job_box.find("div", class_="search-results-job-box-closingdate")
    if closing_date_elem:
        date_text = closing_date_elem.get_text(strip=True)
        try:
            # Remove any "Closing date: " prefix
            if ":" in date_text:
                date_text = date_text.split(":", 1)[1].strip()
            
            # Remove the time prefix and day of the week if present
            if " on " in date_text:
                date_text = date_text.split(" on ", 1)[1].strip()

            # Remove any day of week if present
            if any(day in date_text for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']):
                date_text = ' '.join(date_text.split(' ')[1:])
                
            # Extract day, month, year
            day = ''.join(c for c in date_text.split()[0] if c.isdigit())
            month = date_text.split()[1]
            year = date_text.split()[2]
            date_text = f"{day} {month} {year}"
            closing_date = datetime.strptime(date_text.strip(), '%d %B %Y').strftime('%Y-%m-%d')
        except Exception as e:
            print(f"Error parsing date '{date_text}': {e}")
    
    job_data = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'title': job_title,
        'department': department,
        'closing_date': closing_date,
        'url': job_link,
        'salary_min': salary_min,
        'salary_max': salary_max,
        'location': location,
        'reference': reference,
        'pdf_path': '',  # Will be updated after saving PDF
    }
    
    print(f"\nFound job in search results:")
    print(f"  Job title:  {job_title}")
    print(f"  Department: {department}")
    print(f"  Salary:     £{salary_min} - £{salary_max}")
    print(f"  Location:   {location}")
    print(f"  Closes:     {closing_date}")
    print(f"  Reference:  {reference}")
    
    return job_data
            

def extract_salary_range(soup):
    """Extract minimum and maximum salary from the job page."""
    salary_text = soup.get_text(strip=True)

    # Remove the prefix if present
    match = re.search(r'(?:Salary)\s?:\s*(.*)', salary_text, re.IGNORECASE)
    salary_text = match.group(1).strip() if match else salary_text

    # Common patterns for salary ranges
    patterns = [
        r'£([\d,]+)(?:\s*-\s*£?([\d,]+))',  # £30,000 - £40,000
        r'£([\d,]+)(?:\s*to\s*£?([\d,]+))', # £30,000 to £40,000
        r'Up to £([\d,]+)',  # Up to £40,000
        r'From £([\d,]+)',   # From £30,000
        r'£([\d,]+)',        # £20,000
    ]
    
    for pattern in patterns:
        match = re.search(pattern, salary_text)
        if match:
            groups = match.groups()
            min_salary = groups[0].replace(',', '') if groups[0] else None
            max_salary = groups[1].replace(',', '') if len(groups) > 1 and groups[1] else min_salary
            return min_salary, max_salary
            
    return salary_text, None

def extract_reference(ref_elem):
    ref_text = ref_elem.get_text(strip=True)
    match = re.search(r'(?:Reference|Ref|Reference number)\s?:\s*([^\s]+)', ref_text, re.IGNORECASE)
    return match.group(1) if match else ref_text

def scrape_job_page(job_data, output_folder, file_list, jobs_google_sheet, dry_run):
    print(f"\nFetching job page: {job_data['url']}")
    
    response = requests_session.get(job_data['url'], headers=HEADERS)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    try:
        # Save PDF
        pdf_result = save_job_as_pdf(response.text, job_data['title'], job_data['department'], 
                                     job_data['closing_date'], output_folder, file_list, dry_run)
        
        if pdf_result == ScrapeResult.NEW:
            # Update PDF path
            job_data['pdf_path'] = os.path.join(output_folder, 
                sanitize_filename(f"{job_data['closing_date'] or datetime.now().strftime('%Y-%m-%d')} {job_data['title']} - {job_data['department']}.pdf"))
            
            success = jobs_google_sheet.update_job_in_sheet(job_data, dry_run)
            return success
        return False
    except Exception as e:
        print(f"Error saving PDF: {e}")
        return False

class JobsGoogleSheet:
    def __init__(self):
        self.service = self._initialize_service()
        # Map of sheet column names to job_data keys
        self.column_mapping = {
            'scrape date': 'date',
            'job title': 'title',
            'department': 'department',
            'closing date': 'closing_date',
            'url': 'url',
            'pdf path': 'pdf_path',
            'salary min': 'salary_min',
            'salary max': 'salary_max',
            'location': 'location',
            'reference': 'reference'
        }
        self.init_job_index()

    def _initialize_service(self):
        """Initialize and return Google Sheets service."""
        try:
            # Load credentials from service account file
            key_path = os.path.expanduser('~/.gcloud/job-scraper-service-account-key.json')
            if os.path.exists(key_path):
                # for local use
                creds = ServiceAccountCredentials.from_service_account_file(
                    key_path,
                    scopes=SCOPES
                )
            else:
                # for GitHub Actions use
                service_account_info = os.environ.get('GOOGLE_SERVICE_ACCOUNT_KEY')
                if not service_account_info:
                    raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY environment variable not found")
                service_account_dict = json.loads(service_account_info)
                creds = ServiceAccountCredentials.from_service_account_info(
                    service_account_dict,
                    scopes=SCOPES
                )

            # Build the service
            service = build('sheets', 'v4', credentials=creds)
            return service
        except Exception as e:
            print(f"Error initializing Sheets service: {e}")
            return None

    def get_job_row(self, job_data):
        lookup_key = self._job_lookup_keys(job_data)[0]
        if lookup_key is None:
            lookup_key = self._job_lookup_keys(job_data)[1]
        return self.job_index.get(lookup_key)

    def _job_lookup_keys(self, job_data):
        return (
            job_data.get('reference'),
            (job_data['title'], job_data['department'], job_data['closing_date'])
        )
    
    def add_job_to_index(self, job_data, row_number):
        for lookup_key in self._job_lookup_keys(job_data):
            self.job_index[lookup_key] = row_number
        self.num_jobs += 1

    def init_job_index(self):
        """Fetch existing jobs from the sheet."""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGE_NAME
            ).execute()
            
            rows = result.get('values', [])
            if not rows:
                print("No data found in sheet")
                return {}
            
            self.headers = rows[0]
       
            # Create column index mapping
            self.column_indexes = {header.lower(): idx for idx, header in enumerate(self.headers)}
            required_headers = {'job title', 'department', 'closing date', 'salary min', 'salary max', 
                            'location', 'reference', 'url', 'pdf path', 'scrape date'}
            missing_headers = required_headers - set(h.lower() for h in self.headers)
            if missing_headers:
                print(f"Found headers: {self.headers}")
                raise ValueError(f"Sheet is missing required headers: {missing_headers}")
            
            # Create an index of jobs
            self.job_index = {}
            self.num_jobs = 0
            for i, row in enumerate(rows[1:]):  # Skip header row
                job_data = {self.column_mapping[header]: row[self.column_indexes[header]]
                            for header in required_headers
                            if self.column_indexes[header] < len(row)}
                self.add_job_to_index(job_data, row_number=i+2)
                
            return self.job_index
        except Exception as e:
            print(f"Error fetching existing jobs: {e}")
            return []
        
    def append_to_sheets(self, job_data, dry_run):
        """Append a job to Google Sheets."""
        try:
            # Build row based on header order
            row = []
            for header in self.headers:
                header_lower = header.lower()
                if header_lower in self.column_mapping:
                    value = job_data.get(self.column_mapping[header_lower], '')
                    row.append(value if value is not None else '')
                else:
                    print(f"Warning: Unexpected column header found: {header}")
                    row.append('')
            
            body = {
                'values': [row]
            }
            
            if not dry_run:
                result = self.service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=RANGE_NAME,
                    valueInputOption='RAW',
                    insertDataOption='INSERT_ROWS',
                    body=body
                ).execute()
                
                # Extract the row number from the result
                updated_range = result['updates']['updatedRange']  # e.g., "Sheet1!A11:D11"
                row_number = int(updated_range.split('!')[1].split(':')[0][1:])

                self.add_job_to_index(job_data, row_number)

                print(f"Appended job data to Google Sheets, row {row_number}")
                return True
            else:
                print(f"DRY-RUN, but would have: Appended job data to Google Sheets")
                return True
        except HttpError as e:
            print(f"Error appending to Google Sheets: {e}")
            return False

    def update_job_in_sheet(self, job_data, dry_run):
        
        try:
            row_index = self.get_job_row(job_data)
            
            if row_index is not None and not dry_run:
                # Update the PDF path cell
                update_range = f"{chr(65 + self.column_indexes['pdf path'])}{row_index}"
                update_body = {
                    'values': [[job_data['pdf_path']]]
                }
                
                self.service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=update_range,
                    valueInputOption='RAW',
                    body=update_body
                ).execute()
                
                print(f"Updated PDF path in sheet for job: {job_data['title']}")
                return True
            elif dry_run:
                print(f"DRY-RUN, but would have: Updated PDF path in sheet for job: {job_data['title']}")
                return True
            else:
                print(f"Could not find matching row for job: {job_data['title']}")
                return False
                
        except Exception as e:
            print(f"Error updating sheet with PDF path: {e}")
            return False
        
def save_job_as_pdf(input_html, job_title, department, closing_date, output_folder, file_list, dry_run):
    # Create filename with closing date, or today if not available
    date = closing_date or datetime.now().strftime('%Y-%m-%d')
    filename_base = sanitize_filename(f"{date} {job_title} - {department}")
    pdf_file_path = os.path.join(output_folder, f"{filename_base}.pdf")
    github_token = get_github_token()

    if check_if_file_exists(pdf_file_path, file_list):
        print(f"File already exists on GitHub: {pdf_file_path}")
        return ScrapeResult.EXISTING

    if not dry_run:
        try:
            html = HTML(string=input_html)
            html.write_pdf(pdf_file_path)
            print(f"Saved job PDF {pdf_file_path}")
        except Exception as e:
            print(f"Error saving PDF '{pdf_file_path}': {e}")
            raise
    else:
        print(f"DRY-RUN, but would have: Saved job PDF {pdf_file_path}")

    if not dry_run and github_token:
        try:
            upload_to_github(pdf_file_path, github_token)
        except Exception as e:
            print(f"ERROR uploading job PDF {pdf_file_path}: {e}")
            raise Exception("Failed to upload to GitHub")
        print(f"Uploaded job PDF {pdf_file_path}")
        return ScrapeResult.NEW
    elif dry_run:
        print(f"DRY-RUN, but would have: Uploaded job PDF {pdf_file_path}")
        return ScrapeResult.NEW
    else:
        print(f"ERROR: No GitHub token to upload {pdf_file_path}")
        raise Exception("No GitHub token available")


def sanitize_filename(filename):
    # Replace unsafe characters for filenames
    return "".join(c for c in filename if c.isalnum() or c in " ._-()").strip()


def fetch_all_files_from_github(github_token):
    """Fetch a list of all files in the GitHub repository."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/git/trees/{REPO_BRANCH}?recursive=1"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }

    response = requests_session.get(url, headers=headers)
    response.raise_for_status()

    tree = response.json().get("tree", [])
    file_paths = [item["path"] for item in tree if item["type"] == "blob"]
    return file_paths

def check_if_file_exists(file_path, file_list):
    """Check if the file exists in the GitHub file list."""
    return file_path in file_list

def upload_to_github(file_path, github_token):
    
    # Read file content and encode in base64
    with open(file_path, 'rb') as file:
        content = b64encode(file.read()).decode()
    
    # GitHub API call
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "message": f"Add job listing {os.path.basename(file_path)}",
        "content": content,
        "REPO_BRANCH": REPO_BRANCH
    }
    
    response = requests_session.put(url, headers=headers, json=data)
    if response.status_code != 201:
        response.raise_for_status()
        raise Exception(f"Expected 201 status, got {response.status_code} {response.body}")

class RateLimitedRequestsSession(requests.Session):
    def __init__(self, rate_limit_enabled=True, delay=1.0):
        super().__init__()
        self.last_request_time = 0
        self.rate_limit_enabled = rate_limit_enabled
        self.delay = delay

    def request(self, *args, **kwargs):
        if self.rate_limit_enabled:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
        
        response = super().request(*args, **kwargs)
        self.last_request_time = time.time()
        return response

requests_session = RateLimitedRequestsSession(rate_limit_enabled=not os.environ.get("DISABLE_RATELIMITING"))

def get_github_token():
    # try file
    token_filepath = ".github-token"
    if os.path.exists(token_filepath):
        with open(token_filepath, "r") as f:
            return f.read().strip()
        
    # try env variable
    return os.environ.get("GITHUB_TOKEN")

def parse_arguments():
    parser = argparse.ArgumentParser(description='Job scraping script with command line options')
    parser.add_argument('--dry-run', action='store_true', 
                       help="Don't change the spreadsheet or upload PDFs")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    
    try:
        stats = scrape_jobs(
            search_options_list=SEARCH_OPTIONS_LIST,
            dry_run=args.dry_run
        )
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

    if stats.errored:
        sys.exit(1)

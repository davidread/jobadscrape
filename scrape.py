from base64 import b64encode
from collections import defaultdict
from datetime import datetime
from enum import Enum, auto
import os
from pprint import pprint
import re

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
        "output folder": "jobs/gds",
    }, 
    {
        "department": "258439", # "Central Digital and Data Office"
        "output folder": "jobs/cddo",
    },
    {
        "department": "183940", # "Ministry of Justice"
        "type of role": "249407", # digital
        "output folder": "jobs/moj",
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
        
    def add_job(self, department, result):
        self.stats[department][result] += 1
    
    def print_summary(self):
        print("\n=== Scraping Summary ===")
        total_by_result = defaultdict(int)
        
        for dept, counts in self.stats.items():
            total = sum(counts.values())
            
            print(f"\n{dept}:")
            print(f"  Total jobs found: {total}")
            print(f"  New jobs uploaded: {counts[ScrapeResult.NEW]} ({(counts[ScrapeResult.NEW]/total * 100):.1f}%)")
            print(f"  Existing jobs: {counts[ScrapeResult.EXISTING]}")
            if counts[ScrapeResult.ERROR]:
                print(f"  ERRORS: {counts[ScrapeResult.ERROR]} ({(counts[ScrapeResult.ERROR]/total * 100):.1f}%)")
            
            for result, count in counts.items():
                total_by_result[result] += count
        
        total_jobs = sum(total_by_result.values())
        print("\nOverall Summary:")
        print(f"  Total jobs across all departments: {total_jobs}")
        print(f"  Total new jobs uploaded: {total_by_result[ScrapeResult.NEW]} ({(total_by_result[ScrapeResult.NEW]/total_jobs * 100):.1f}%)")
        print(f"  Total existing jobs: {total_by_result[ScrapeResult.EXISTING]}")
        errors = total_by_result[ScrapeResult.ERROR]
        if errors:
            print(f"  ERRORS: {errors} ({(errors/total_jobs * 100):.1f}%)")
        print("=====================")

def scrape_jobs(search_options_list):
    print("Starting job scraping...")
    stats = ScrapingStats()

    # Fetch a list of PDFs already in GitHub
    github_token = os.environ.get("GITHUB_TOKEN")
    file_list = fetch_all_files_from_github(github_token) if github_token else []

    # Initialize Google Sheets service
    sheets_service = initialize_sheets_service()
    if not sheets_service:
        print("Warning: Google Sheets service not initialized. Will continue without saving to sheets.")
        existing_jobs = {}
    else:
        headers, existing_jobs = get_existing_jobs(sheets_service)
        print(f"Found {len(existing_jobs)} existing jobs in sheet")
   
    sid = get_fresh_sid()
    reqsig = get_reqsig(sid)

    for search_options in search_options_list:
        output_folder = search_options.get("output folder")
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
        department = search_options.get("department")
        if department:
            payload["nghr_dept"] = department
        if "type of role" in search_options:
            payload["nghr_job_category"] = search_options["type of role"]
            
        response = requests.post(search_url, data=payload, headers=HEADERS)
        response.raise_for_status()
        
        # Parse search results
        soup = BeautifulSoup(response.text, "html.parser")
        job_result = soup.find_all("li", class_="search-results-job-box")
        print(f"\nSearch: {search_options}")
        print(f"Found {len(job_result)} job listings")

        for job_result in job_result:
            try:
                # Extract info from search result
                job_data = scrape_job_search_result(job_result, existing_jobs)
                
                # Check if job already exists in the sheet
                job_key = (job_data['title'], job_data['department'], job_data['closing_date'])
                if job_key in existing_jobs:
                    print(f"Job already exists in sheet: {job_data['title']}")
                    stats.add_job(job_data['department'], ScrapeResult.EXISTING)
                    continue
                
                # Add to sheet
                if sheets_service and append_to_sheets(sheets_service, job_data, headers):
                    # If successfully added to sheet, fetch full page and save PDF
                    if scrape_job_page(job_data, output_folder, file_list, sheets_service):
                        stats.add_job(job_data['department'], ScrapeResult.SHEET_UPDATED)
                    else:
                        stats.add_job(job_data['department'], ScrapeResult.ERROR)
                else:
                    stats.add_job(job_data['department'], ScrapeResult.ERROR)
                    
            except Exception as e:
                print(f"Error processing job box: {e}")
                stats.add_job(department, ScrapeResult.ERROR)

    # Print summary at the end
    stats.print_summary()
    return stats

def get_fresh_sid():
    """Fetch a fresh SID from the website."""
    initial_url = f"{BASE_URL}/csr/index.cgi"
    response = requests.get(initial_url, headers=HEADERS)
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
    response = requests.get(url, params=params, headers=HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    return extract_reqsig(soup)

def extract_reqsig(soup):
    reqsig_input = soup.find("input", {"name": "reqsig"})
    assert reqsig_input
    reqsig = reqsig_input["value"]
    return reqsig

def scrape_job_search_result(job_box, existing_jobs):
    """Extract job information from a search result box."""
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
            
def get_existing_jobs(service):
    """Fetch existing jobs from the sheet to check for duplicates."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE_NAME
        ).execute()
        
        rows = result.get('values', [])
        if not rows:
            print("No data found in sheet")
            return [], {}
            
        # Get headers from first row
        headers = rows[0]
        print(f"Found headers: {headers}")
        
        # Create column index mapping
        col_map = {header.lower(): idx for idx, header in enumerate(headers)}
        required_headers = {'job title', 'department', 'closing date', 'salary min', 'salary max', 
                          'location', 'reference', 'url', 'pdf path', 'scrape date'}
        missing_headers = required_headers - set(h.lower() for h in headers)
        if missing_headers:
            raise ValueError(f"Sheet is missing required headers: {missing_headers}")
        
        # Create a set of tuples (job title, department, closing_date) for easy matching
        existing_jobs = {
            (
                row[col_map['job title']], 
                row[col_map['department']], 
                row[col_map['closing date']]
            ): {
                'salary_min': row[col_map['salary min']] if len(row) > col_map['salary min'] else None,
                'salary_max': row[col_map['salary max']] if len(row) > col_map['salary max'] else None,
                'location': row[col_map['location']] if len(row) > col_map['location'] else None,
                'reference': row[col_map['reference']] if len(row) > col_map['reference'] else None
            }
            for row in rows[1:]  # Skip header row
            if len(row) > max(col_map['job title'], col_map['department'], col_map['closing date'])
        }
        
        return headers, existing_jobs
    except Exception as e:
        print(f"Error fetching existing jobs: {e}")
        return []

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
        r'From £([\d,]+)'    # From £30,000
        r'£([\d,]+)'         # £20,000
    ]
    
    for pattern in patterns:
        match = re.search(pattern, salary_text)
        if match:
            groups = match.groups()
            min_salary = groups[0].replace(',', '') if groups[0] else None
            max_salary = groups[1].replace(',', '') if len(groups) > 1 and groups[1] else min_salary
            return min_salary, max_salary
            
    return salary_text, None

def scrape_job_page(job_data, output_folder, file_list, sheets_service):
    print(f"\nFetching job page: {job_data['url']}")
    
    response = requests.get(job_data['url'], headers=HEADERS)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    try:
        # Save PDF
        pdf_result = save_job_as_pdf(response.text, job_data['title'], job_data['department'], 
                                   job_data['closing_date'], output_folder, file_list)
        
        if pdf_result == ScrapeResult.NEW:
            # Update PDF path
            job_data['pdf_path'] = os.path.join(output_folder, 
                sanitize_filename(f"{job_data['closing_date'] or datetime.now().strftime('%Y-%m-%d')} {job_data['title']} - {job_data['department']}.pdf"))
            return True
            
        return False
    except Exception as e:
        print(f"Error saving PDF: {e}")
        return False


def initialize_sheets_service():
    """Initialize and return Google Sheets service."""
    try:
        # Load credentials from service account file
        if os.path.exists('job-scraper-service-account-key.json'):
            # for local use
            creds = ServiceAccountCredentials.from_service_account_file(
                'job-scraper-service-account-key.json',
                scopes=SCOPES
            )
        else:
            # for GitHub Actions use
            service_account_info = os.environ.get('GOOGLE_SERVICE_ACCOUNT_KEY')
            if not service_account_info:
                raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY environment variable not found")
            service_account_dict = json.loads(service_account_info)
            creds = ServiceAccountCredentials.from_dict(
                service_account_dict,
                scopes=SCOPES
            )

        # Build the service
        service = build('sheets', 'v4', credentials=creds)
        return service
    except Exception as e:
        print(f"Error initializing Sheets service: {e}")
        return None

def append_to_sheets(service, job_data, headers):
    """Append a row of job data to Google Sheets."""
    try:
        # Create a mapping of expected column names to job_data keys
        column_mapping = {
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
        
        # Build row based on header order
        row = []
        for header in headers:
            header_lower = header.lower()
            if header_lower in column_mapping:
                value = job_data.get(column_mapping[header_lower], '')
                row.append(value if value is not None else '')
            else:
                print(f"Warning: Unexpected column header found: {header}")
                row.append('')
        
        body = {
            'values': [row]
        }
        
        result = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE_NAME,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        # Extract the row number from the result
        updated_range = result['updates']['updatedRange']  # e.g., "Sheet1!A11:D11"
        row_number = int(updated_range.split('!')[1].split(':')[0][1:])

        print(f"Appended job data to Google Sheets, row {row_number}")
        return True
    except HttpError as e:
        print(f"Error appending to Google Sheets: {e}")
        return False

def save_job_as_pdf(input_html, job_title, department, closing_date, output_folder, file_list):
    # Create filename with closing date, or today if not available
    date = closing_date or datetime.now().strftime('%Y-%m-%d')
    filename_base = sanitize_filename(f"{date} {job_title} - {department}")
    pdf_file_path = os.path.join(output_folder, f"{filename_base}.pdf")
    github_token = os.environ.get("GITHUB_TOKEN")

    if check_if_file_exists(pdf_file_path, file_list):
        print(f"File already exists on GitHub: {pdf_file_path}")
        return ScrapeResult.EXISTING

    try:
        html = HTML(string=input_html)
        html.write_pdf(pdf_file_path)
        print(f"Saved job PDF {pdf_file_path}")
    except Exception as e:
        print(f"Error saving PDF '{pdf_file_path}': {e}")
        raise

    if github_token:
        success = upload_to_github(pdf_file_path, github_token)
        if success:
            print(f"Uploaded job PDF {pdf_file_path}")
            return ScrapeResult.NEW
        else:
            print(f"ERROR uploading job PDF {pdf_file_path}")
            raise Exception("Failed to upload to GitHub")
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

    response = requests.get(url, headers=headers)
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
    
    response = requests.put(url, headers=headers, json=data)
    return response.status_code == 201


if __name__ == "__main__":
    try:
        scrape_jobs(search_options_list=SEARCH_OPTIONS_LIST)
    except Exception as e:
        print(f"An error occurred: {e}")

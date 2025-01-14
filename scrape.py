from base64 import b64encode
from collections import defaultdict
from datetime import datetime
from enum import Enum, auto
import os
from pprint import pprint

import requests
from bs4 import BeautifulSoup
from weasyprint import HTML

# Previous constants remain the same
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
REPO_OWNER = "davidread"
REPO_NAME = "jobadscrape"
REPO_BRANCH = "main"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0"
}

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

    # Fetch a list of files from GitHub once
    github_token = os.environ.get("GITHUB_TOKEN")
    file_list = fetch_all_files_from_github(github_token) if github_token else []
    
    sid = get_fresh_sid()
    print(f"Fresh SID: {sid}")
    reqsig = get_reqsig(sid)

    for search_options in search_options_list:
        # Send GET request to the Civil Service Jobs search page
        search_url = f"{BASE_URL}/csr/esearch.cgi"
        params = {"SID": sid}
        print(f'url={requests.Request("GET", search_url, params=params).prepare().url}')

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
        if "output folder" in search_options:
            output_folder = search_options.pop("output folder")
            os.makedirs(output_folder, exist_ok=True)
        assert not search_options, f"Unprocessed options {search_options}"

        response = requests.post(search_url, data=payload, headers=HEADERS)
        response.raise_for_status()

        # Parse the HTML using BeautifulSoup
        soup = BeautifulSoup(response.text, "html.parser")

        # Find all job listings
        job_boxes = soup.find_all("li", class_="search-results-job-box")
        print(f"Found {len(job_boxes)} job listings.")

        job_links = []
        for job in job_boxes:
            # Extract job title and link
            title_tag = job.find("h3", class_="search-results-job-box-title")
            job_title = title_tag.get_text(strip=True)
            job_link = title_tag.find("a")["href"]

            # Extract department
            department = job.find("div", class_="search-results-job-box-department").get_text(strip=True)

            print(f"Job '{job_title}' from department '{department}'")
            job_links.append(job_link)

        for job_url in job_links:
            try:
                result = scrape_job_details(job_url, output_folder, file_list)
                stats.add_job(department, result)
            except Exception as e:
                print(f"Error processing job {job_url}: {e}")
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
        print("SID from input field")
        return sid_input["value"]

    # Option 2: Extract SID from the URL in the "action" or "form" element
    form_action = soup.find("form")["action"]
    if "SID=" in form_action:
        print("SID from form URL")
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


def scrape_job_details(job_url, output_folder, file_list):
    print(f"\nFetching job details from: {job_url}")

    response = requests.get(job_url, headers=HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract job details
    job_title = soup.find('h1', {'id': 'id_common_page_title_h1'}).get_text(strip=True)
    department = soup.find('p', {'class': 'csr-page-subtitle'}).get_text(strip=True)

    # Extract closing date using the correct class
    closing_date_elem = soup.find('p', {'class': 'vac_display_closing_date'})
    if closing_date_elem:
        date_text = closing_date_elem.get_text(strip=True)
        try:
            # Remove the "Apply before " prefix and time portion
            date_text = date_text.split(' on ')[-1]  # Get the part after " on "
            # Remove day of week if present (e.g., "Sunday")
            if any(day in date_text for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']):
                date_text = ' '.join(date_text.split(' ')[1:])
            # Remove ordinal suffixes (th/st/nd/rd) but keep the month name
            day = ''.join(c for c in date_text.split()[0] if c.isdigit())
            month = date_text.split()[1]
            year = date_text.split()[2]
            date_text = f"{day} {month} {year}"
            closing_date = datetime.strptime(date_text.strip(), '%d %B %Y').strftime('%Y-%m-%d')
        except Exception as e:
            print(f"Error parsing date '{date_text}': {e}")

    print(f"Processing job: {job_title} from department: {department}, closing: {closing_date}")

    try:
        return save_job_as_pdf(response.text, job_title, department, closing_date, output_folder, file_list)
    except Exception as e:
        print(f"Error saving job: {e}")
        return ScrapeResult.ERROR

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

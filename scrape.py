from pprint import pprint
import os
import requests
from bs4 import BeautifulSoup
from weasyprint import HTML

# Search options
SEARCH_OPTIONS_LIST = [
    {"department": "256999"}, # "Government Digital Service"
    {"department": "258439"}, # "Central Digital and Data Office"
]

# Base URL of the job search site
BASE_URL = "https://www.civilservicejobs.service.gov.uk"

# Folder to save the PDFs
OUTPUT_FOLDER = "jobs"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0"
}

def scrape_jobs(search_options_list):
    print("Starting job scraping...")

    # Setup
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
        assert not search_options, f"Unprocessed options {search_options}"

        pprint(payload)
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
            scrape_job_details(job_url)


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


def scrape_job_details(job_url):
    print(f"Fetching job details from: {job_url}")

    response = requests.get(job_url, headers=HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract job details
    job_title = soup.find('h1', {'id': 'id_common_page_title_h1'}).get_text(strip=True)
    department = soup.find('p', {'class': 'csr-page-subtitle'}).get_text(strip=True)

    print(f"Processing job: {job_title} from department {department}")

    # Save job details as a PDF
    save_job_as_pdf(response.text, job_title, department)


def save_job_as_pdf(input_html, job_title, department):
    filename_base = sanitize_filename(f"{job_title} - {department}")
    pdf_file_name = os.path.join(OUTPUT_FOLDER, f"{filename_base}.pdf")

    try:
        # Convert HTML to PDF using WeasyPrint
        html = HTML(string=input_html)  # Use string if you're passing HTML content directly
        html.write_pdf(pdf_file_name)
        print(f"Saved job PDF {pdf_file_name}")
    except Exception as e:
        print(f"Error saving PDF '{pdf_file_name}': {e}")


def sanitize_filename(filename):
    # Replace unsafe characters for filenames
    return "".join(c for c in filename if c.isalnum() or c in " ._-()").strip()


if __name__ == "__main__":
    try:
        scrape_jobs(search_options_list=SEARCH_OPTIONS_LIST)
    except Exception as e:
        print(f"An error occurred: {e}")

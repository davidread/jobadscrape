import unittest
from bs4 import BeautifulSoup
from datetime import datetime

# Import the function to test
from scrape import scrape_job_search_result, extract_salary_range, extract_reference

class TestJobScraping(unittest.TestCase):
    def setUp(self):
        # Sample HTML for a job listing
        self.sample_html = """
        <li class="search-results-job-box" title="Head of Category / International Development Programmes ">
            <div class="search-results-job-box-logo-legacy">
                <img alt="" class="search-results-job-box-logo-image-legacy" 
                    src="https://static.civilservicejobs.service.gov.uk/company/nghr/sp/images/logos/257668.png" 
                    title="Government Commercial Function Logo">
            </div>
            <div>
                <h3 class="search-results-job-box-title">
                    <a href="https://www.civilservicejobs.service.gov.uk/csr/index.cgi?SID=dXNlcnNlYXJjaGNvbnRleHQ9MTEzMjMxODU0JnBhZ2VjbGFzcz1Kb2JzJmpvYmxpc3Rfdmlld192YWM9MTkzNDgzMSZwYWdlYWN0aW9uPXZpZXd2YWNieWpvYmxpc3Qmc2VhcmNoc29ydD1zY29yZSZzZWFyY2hwYWdlPTEmb3duZXI9NTA3MDAwMCZvd25lcnR5cGU9ZmFpciZyZXFzaWc9MTczNjkzMjcyMi04YzE5MmZkOGMzYjQzM2MxNjE5YTU0NTFiMTJlYTI0OTRmYTBjMTQ2" 
                    title="Head of Category / International Development Programmes ">
                    Head of Category / International Development Programmes 
                    </a>
                </h3>
            </div>
            <div class="search-results-job-box-department">Government Commercial Function</div>
            <div class="search-results-job-box-location">Abercrombie House, East Kilbride, Glasgow (moving to Glasgow City Centre 2025/26) Or King Charles Street, London</div>
            <div class="search-results-job-box-salary">Salary : £80,000 to £97,760</div>
            <div class="search-results-job-box-closingdate">Closes : 11:55 pm on Wednesday 22nd January 2025</div>
            <div class="search-results-job-box-refcode">Reference : 384891</div>
        </li>
        """
        self.soup = BeautifulSoup(self.sample_html, 'html.parser')

    def test_scrape_job_search_result(self):
        # Call the function with our sample data
        job_data = scrape_job_search_result(self.soup, {})

        # Assert all the expected fields are present and correct
        self.assertEqual(job_data['title'], 'Head of Category / International Development Programmes')
        self.assertEqual(job_data['department'], 'Government Commercial Function')
        self.assertEqual(job_data['location'], 
            'Abercrombie House, East Kilbride, Glasgow (moving to Glasgow City Centre 2025/26) Or King Charles Street, London')
        self.assertEqual(job_data['salary_min'], '80000')
        self.assertEqual(job_data['salary_max'], '97760')
        self.assertEqual(job_data['closing_date'], '2025-01-22')
        self.assertEqual(job_data['reference'], '384891')
        self.assertTrue(job_data['url'].startswith('https://www.civilservicejobs.service.gov.uk/csr/index.cgi?SID='))
        
        # Check that the date field is today's date
        today = datetime.now().strftime('%Y-%m-%d')
        self.assertEqual(job_data['date'], today)

    def test_extract_salary_range(self):
        # Test different salary format variations
        salary_variants = [
            ('Salary : £30,000', '30000', '30000'),
            ('Salary : £30,000 to £40,000', '30000', '40000'),
            ('£30,000 - £40,000', '30000', '40000'),  # job page
        ]

        for salary_text, expected_min, expected_max in salary_variants:
            with self.subTest(salary_text=salary_text):
                salary_min, salary_max = extract_salary_range(BeautifulSoup(
                    f'<div class="search-results-job-box-salary">{salary_text}</div>', 
                    'html.parser'
                ))
                self.assertEqual(salary_min, expected_min)
                self.assertEqual(salary_max, expected_max)

    def test_extract_reference(self):
        reference_variants = [
            ('Reference : 381753', '381753'),
            ('382518', '382518'),  # job page
        ]

        for reference_text, expected in reference_variants:
            soup = BeautifulSoup(
                f'<div class="search-results-job-box-refcode">{reference_text}</div>',
                'html.parser'
            )
            with self.subTest(reference_text=soup):
                reference = extract_reference(soup)
                self.assertEqual(reference, expected)

    def test_closing_date_variants(self):
        date_variants = [
            ('Closes : 11:55 pm on Wednesday 22nd January 2025', '2025-01-22'),
            ('Closes : Midday on Monday 3rd February 2025', '2025-02-03'),
            ('Apply before 11:55 pm on Friday 17th January 2025', '2025-01-17'),  # job page
        ]

        for date_text, expected_date in date_variants:
            with self.subTest(date_text=date_text):
                # Create a new soup with the test date
                html = self.sample_html.replace(
                    'Closes : 11:55 pm on Wednesday 22nd January 2025',
                    date_text
                )
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract job data and check date
                job_data = scrape_job_search_result(soup, {})
                self.assertEqual(job_data['closing_date'], expected_date)

if __name__ == '__main__':
    unittest.main()

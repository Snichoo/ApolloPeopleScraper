import os
import json
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)

# Load config data from environment variables
config = {
    'email': os.environ.get('APOLLO_EMAIL'),  # Set 'APOLLO_EMAIL' in environment variables
    'password': os.environ.get('APOLLO_PASSWORD')  # Set 'APOLLO_PASSWORD' in environment variables
}

# Constants
STORAGE_STATE_PATH = 'apollo_login.json'

def init_browser(playwright_instance):
    print("Starting browser...")
    if os.path.exists(STORAGE_STATE_PATH):
        print("Storage state file found. Using saved session.")
        browser = playwright_instance.chromium.launch(headless=False)
        context = browser.new_context(storage_state=STORAGE_STATE_PATH)
        page = context.new_page()
    else:
        print("No storage state file found. Logging in manually.")
        browser = playwright_instance.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        login_to_site(page)
        # Save the authenticated state
        context.storage_state(path=STORAGE_STATE_PATH)
        print(f"Saved storage state to {STORAGE_STATE_PATH}")
    return browser, context, page

def login_to_site(page):
    print("Starting login process...")
    page.goto('https://app.apollo.io/#/login')

    # Wait for the login form to be present
    print("Waiting for login form to be present...")
    page.wait_for_selector("input[name='email']")

    print("Filling in email and password...")
    page.fill("input[name='email']", config['email'])
    page.fill("input[name='password']", config['password'])
    print("Submitting login form...")
    page.click("button[type='submit']")

    # Wait for the URL to change indicating successful login
    print("Waiting for login to complete...")
    try:
        page.wait_for_url('https://app.apollo.io/#/home', timeout=30000)
        print("Login successful.")
    except Exception as e:
        print(f"Login failed: {e}")
        raise Exception("Login failed.")

def scrape_contacts(page, domain_name):
    print("Navigating to the initial page...")
    page.goto('https://app.apollo.io/#/people?page=1&sortAscending=false&sortByField=%5Bnone%5D')
    page.wait_for_load_state('networkidle')
    page.wait_for_selector("body")

    # Click on "Company" filter
    print("Attempting to click on 'Company' filter...")
    try:
        company_filter = page.wait_for_selector("//span[text()='Company']", timeout=5000)
        company_filter.click()
    except Exception as e:
        print(f"Could not click on 'Company' filter: {e}")
        # Try again after 1 second
        page.wait_for_timeout(1000)
        try:
            company_filter = page.wait_for_selector("//span[text()='Company']", timeout=5000)
            company_filter.click()
        except Exception as e:
            print(f"Second attempt failed to click on 'Company' filter: {e}")
            raise Exception("Could not find 'Company' filter element")

    # Find the input field that says 'Enter companies...'
    print("Looking for 'Enter companies...' input field...")

    try:
        # Wait for the input field to be visible
        page.wait_for_selector("input.Select-input", timeout=10000)
        # Type the domain name
        page.fill("input.Select-input", domain_name)
        # Wait for the dropdown options to appear
        print("Waiting for suggestions to appear...")
        suggestion_selector = f"//div[contains(@class, 'Select-option') and contains(., '{domain_name}')]"
        page.wait_for_selector(suggestion_selector, timeout=5000)
        # Click on the matching suggestion
        print("Selecting the company from suggestions...")
        page.click(suggestion_selector)
    except Exception as e:
        print(f"Could not select company: {e}")
        # Try again after 1 second
        page.wait_for_timeout(1000)
        try:
            page.fill("input.Select-input", domain_name)
            print("Waiting for suggestions to appear...")
            page.wait_for_selector(suggestion_selector, timeout=5000)
            print("Selecting the company from suggestions...")
            page.click(suggestion_selector)
        except Exception as e:
            print(f"Second attempt failed to select company: {e}")
            raise Exception("Could not select the company from suggestions")

    # Wait for URL to change and include organizationIds[]
    print("Waiting for URL to include 'organizationIds[]'...")
    try:
        page.wait_for_url("**organizationIds[]**", timeout=10000)
    except Exception as e:
        print(f"URL did not change as expected: {e}")
        raise Exception("URL did not change to include 'organizationIds[]'")

    # Extract organizationIds from the URL
    current_url = page.url
    print(f"Current URL: {current_url}")
    parsed_url = urlparse(current_url)

    # Check if query parameters are in the query or fragment
    if parsed_url.query:
        query_params = parse_qs(parsed_url.query)
    else:
        # Query parameters are in the fragment
        fragment_parsed = urlparse(parsed_url.fragment)
        query_params = parse_qs(fragment_parsed.query)

    organization_ids = query_params.get('organizationIds[]', [])
    if organization_ids:
        organization_id = organization_ids[0]
        print(f"Organization ID: {organization_id}")
    else:
        raise Exception("Could not find organizationIds in URL")

    # Now, on the page, scrape each contact's Name, Job Title, LinkedIn, Company Number of Employees
    print("Waiting for contacts to load...")
    page.wait_for_selector("div[role='rowgroup']")

    print("Scraping contacts...")
    rows = page.query_selector_all("div[role='row'][id^='table-row-']")

    contacts = []

    for row in rows:
        # For each row, extract the data
        cells = row.query_selector_all("div[role='gridcell']")

        # Ensure there are enough cells
        if len(cells) < 9:
            continue

        # Name
        name_cell = cells[1]
        name = name_cell.inner_text().strip()

        # Job title
        job_title_cell = cells[2]
        job_title = job_title_cell.inner_text().strip()

        # LinkedIn link
        linkedin_cell = cells[7]
        linkedin_link = None
        linkedin_anchor = linkedin_cell.query_selector("a[aria-label='linkedin']")
        if linkedin_anchor:
            linkedin_link = linkedin_anchor.get_attribute("href")

        # Company Number of Employees (assuming it's in cell[8])
        number_of_employees_cell = cells[9]
        number_of_employees = number_of_employees_cell.inner_text().strip()

        contact = {
            'name': name,
            'job_title': job_title,
            'linkedin': linkedin_link,
            'number_of_employees': number_of_employees
        }
        contacts.append(contact)

    print(f"Scraped {len(contacts)} contacts.")
    return {'organization_id': organization_id, 'contacts': contacts}

@app.route('/scrape_contacts', methods=['POST'])
def scrape_contacts_endpoint():
    data = request.json
    domain_name = data.get('domain_name')

    if not domain_name:
        print("Missing domain_name parameter in request.")
        return jsonify({'error': 'Missing domain_name parameter'}), 400

    print(f"Processing request to scrape contacts for domain: {domain_name}")

    with sync_playwright() as playwright_instance:
        browser = None
        context = None
        try:
            browser, context, page = init_browser(playwright_instance)
            result = scrape_contacts(page, domain_name)
            return jsonify(result)
        except Exception as e:
            print(f"An error occurred during scraping: {e}")
            return jsonify({'error': str(e)}), 500
        finally:
            if context:
                context.close()
            if browser:
                browser.close()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Flask app on port {port}...")
    app.run(host='0.0.0.0', port=port, threaded=True)

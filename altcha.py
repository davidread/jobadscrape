import asyncio
import random
import time
from playwright.async_api import async_playwright, Page, Response
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class CaptchaTestError(Exception):
    """Base exception for captcha testing errors"""
    pass


class CaptchaTester:
    def __init__(self, captcha_page_url: str, challenge_url_pattern: str = "ProtectCaptcha=1"):
        self.captcha_page_url = captcha_page_url
        self.challenge_url_pattern = challenge_url_pattern
        self.challenge_response: Optional[Dict[Any, Any]] = None
        
    async def random_delay(self, min_ms: int, max_ms: int):
        """Add a random human-like delay"""
        delay = random.uniform(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)
    
    async def response_handler(self, response: Response):
        """Intercept and capture ALTCHA challenge responses"""
        try:
            url = response.url
            if self.challenge_url_pattern in url:
                logger.info(f"📡 Captured ALTCHA challenge endpoint: {url}")
                try:
                    self.challenge_response = await response.json()
                    logger.info(f"📦 Challenge data received: {list(self.challenge_response.keys()) if isinstance(self.challenge_response, dict) else 'data'}")
                except Exception as e:
                    logger.warning(f"Challenge response was not JSON: {e}")
                    try:
                        text_response = await response.text()
                        self.challenge_response = {"raw": text_response}
                        logger.info(f"📦 Challenge text data: {text_response[:100]}...")
                    except:
                        pass
        except Exception as e:
            logger.error(f"Error in response handler: {e}")
    
    async def move_mouse_naturally(self, page: Page, target_x: int, target_y: int):
        """Move mouse along a curved path to target"""
        try:
            # Get current mouse position (start from a random position if unknown)
            start_x = random.randint(100, 500)
            start_y = random.randint(100, 300)
            
            # Create a curved path with multiple steps
            steps = random.randint(15, 25)
            for i in range(steps):
                progress = i / steps
                # Add some curve to the movement (bezier-like)
                curve_offset = 30 * (4 * progress * (1 - progress))
                
                current_x = start_x + (target_x - start_x) * progress
                current_y = start_y + (target_y - start_y) * progress + curve_offset
                
                await page.mouse.move(current_x, current_y)
                await asyncio.sleep(random.uniform(0.005, 0.015))
            
            # Final move to exact target
            await page.mouse.move(target_x, target_y)
        except Exception as e:
            logger.warning(f"Could not move mouse naturally: {e}")
    
    async def find_and_click_checkbox(self, page: Page):
        """Find and click the ALTCHA checkbox with human-like behavior"""
        try:
            # Wait for the altcha-widget to be present
            logger.info("⏳ Waiting for ALTCHA widget to appear...")
            widget = await page.wait_for_selector("altcha-widget", state="attached", timeout=10000)
            
            if not widget:
                raise CaptchaTestError("ALTCHA widget not found")
            
            logger.info("✓ ALTCHA widget found")
            
            # Look for the checkbox inside the widget
            # Try multiple selectors to find the checkbox
            checkbox_selectors = [
                "altcha-widget input[type='checkbox']",
                "altcha-widget .altcha-checkbox input",
                "input[id^='altcha_checkbox_']"  # Starts with altcha_checkbox_
            ]
            
            checkbox = None
            used_selector = None
            
            for selector in checkbox_selectors:
                try:
                    checkbox = await page.wait_for_selector(selector, state="visible", timeout=2000)
                    if checkbox:
                        used_selector = selector
                        logger.info(f"✓ Found checkbox using selector: {selector}")
                        break
                except:
                    continue
            
            if not checkbox:
                raise CaptchaTestError("Checkbox input not found")
            
            # Check if already checked
            is_checked = await checkbox.is_checked()
            if is_checked:
                logger.info("ℹ️ Checkbox is already checked!")
                return True
            
            # Get checkbox bounding box
            box = await checkbox.bounding_box()
            if not box:
                # Try clicking the label instead
                label = await page.query_selector("altcha-widget .altcha-label")
                if label:
                    box = await label.bounding_box()
                    logger.info("ℹ️ Using label for click target")
                
            if not box:
                raise CaptchaTestError("Could not get checkbox or label position")
            
            # Calculate click position with slight randomization
            # For checkboxes, click slightly offset from center for realism
            click_x = box['x'] + box['width'] / 2 + random.uniform(-3, 3)
            click_y = box['y'] + box['height'] / 2 + random.uniform(-3, 3)
            
            logger.info(f"🖱️  Moving mouse to checkbox at ({click_x:.1f}, {click_y:.1f})")
            await self.move_mouse_naturally(page, click_x, click_y)
            
            # Small pause before clicking (human reads "I'm not a robot")
            await self.random_delay(500, 1200)
            
            # Perform the click with mouse down/up for realism
            logger.info("🖱️  Clicking the checkbox...")
            await page.mouse.down()
            await asyncio.sleep(random.uniform(0.05, 0.12))  # Realistic click duration
            await page.mouse.up()
            
            # Verify the click worked
            await asyncio.sleep(0.3)
            is_checked = await checkbox.is_checked()
            logger.info(f"✓ Checkbox checked status: {is_checked}")
            
            # Small movement away after click
            await page.mouse.move(
                click_x + random.uniform(20, 100),
                click_y + random.uniform(-50, 50)
            )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error clicking checkbox: {e}")
            raise CaptchaTestError(f"Failed to click checkbox: {e}")
    
    async def wait_for_proof_of_work(self, page: Page, timeout_ms: int = 60000):
        """Wait for the proof-of-work to complete"""
        logger.info("⏳ Waiting for proof-of-work computation...")
        start_time = time.time() * 1000
        check_interval = 300
        last_state = None
        check_count = 0
        
        while (time.time() * 1000 - start_time) < timeout_ms:
            check_count += 1
            
            try:
                # PRIMARY CHECK: Look for the hidden input with the proof
                hidden_input = await page.query_selector("altcha-widget input[type='hidden'][name='altcha']")
                if hidden_input:
                    value = await hidden_input.get_attribute("value")
                    if value and len(value) > 50:  # The JWT token is quite long
                        logger.info(f"✅ SUCCESS! Hidden input found with proof-of-work solution")
                        logger.info(f"🔑 Solution token length: {len(value)} characters")
                        return True
                
                # SECONDARY CHECK: data-state="verified"
                widget = await page.query_selector("altcha-widget .altcha[data-state='verified']")
                if widget:
                    logger.info(f"✅ SUCCESS! Widget state is 'verified'")
                    return True
                
                # TERTIARY CHECK: Label text changed to "Verified"
                label = await page.query_selector("altcha-widget .altcha-label")
                if label:
                    label_text = await label.inner_text()
                    if label_text.strip() == "Verified":
                        logger.info(f"✅ SUCCESS! Label changed to 'Verified'")
                        return True
                
                # Check current state for logging
                altcha_div = await page.query_selector("altcha-widget .altcha[data-state]")
                if altcha_div:
                    current_state = await altcha_div.get_attribute("data-state")
                    if current_state != last_state:
                        logger.info(f"📊 Widget state: {current_state}")
                        last_state = current_state
                
                # Log progress every 5 seconds
                elapsed = (time.time() * 1000 - start_time) / 1000
                if check_count % 17 == 0:  # Roughly every 5 seconds (300ms * 17)
                    logger.info(f"⏱️  Still waiting... ({elapsed:.1f}s elapsed)")
                        
            except Exception as e:
                logger.debug(f"Error checking success indicators: {e}")
            
            # Random delay before next check with slight variation
            await asyncio.sleep(check_interval / 1000)
            check_interval = random.uniform(280, 320)
            
            # Occasional micro mouse movement to seem alive
            if random.random() < 0.08:  # 8% chance
                try:
                    current_x = random.randint(400, 800)
                    current_y = random.randint(300, 600)
                    await page.mouse.move(
                        current_x + random.uniform(-10, 10),
                        current_y + random.uniform(-10, 10)
                    )
                except:
                    pass
        
        # Timeout reached
        logger.error("❌ Proof-of-work timeout reached (60 seconds)")
        
        # Try to get final state for debugging
        try:
            altcha_div = await page.query_selector("altcha-widget .altcha[data-state]")
            if altcha_div:
                final_state = await altcha_div.get_attribute("data-state")
                logger.error(f"Final state at timeout: {final_state}")
        except:
            pass
            
        raise CaptchaTestError("Proof-of-work completion timeout after 60 seconds")
    
    async def click_continue_button(self, page: Page):
        """Click the Continue button and verify navigation"""
        try:
            logger.info("🔍 Looking for Continue button...")
            
            # Wait for the continue button
            continue_button = await page.wait_for_selector("button[type='submit']", timeout=5000)
            
            if not continue_button:
                raise CaptchaTestError("Continue button not found")
            
            # Check button text to confirm it's the right one
            button_text = await continue_button.inner_text()
            logger.info(f"✓ Found button with text: '{button_text}'")
            
            # Get button position
            box = await continue_button.bounding_box()
            if not box:
                raise CaptchaTestError("Could not get button position")
            
            # Calculate click position with randomization
            click_x = box['x'] + box['width'] / 2 + random.uniform(-5, 5)
            click_y = box['y'] + box['height'] / 2 + random.uniform(-5, 5)
            
            # Human pause before clicking
            logger.info("⏸️  Pausing to verify captcha completion...")
            await self.random_delay(1000, 2000)
            
            # Move mouse to button
            logger.info(f"🖱️  Moving mouse to Continue button at ({click_x:.1f}, {click_y:.1f})")
            await self.move_mouse_naturally(page, click_x, click_y)
            
            # Small pause before clicking
            await self.random_delay(300, 700)
            
            # Click the button
            logger.info("🖱️  Clicking Continue button...")
            await page.mouse.down()
            await asyncio.sleep(random.uniform(0.06, 0.14))
            await page.mouse.up()
            
            # Wait for navigation or response
            logger.info("⏳ Waiting for page navigation...")
            try:
                # Wait for either navigation or network to be idle
                await page.wait_for_load_state("networkidle", timeout=10000)
                logger.info("✅ Page navigation completed!")

                # Get the new URL
                new_url = page.url
                logger.info(f"🌐 Current URL: {new_url}")
                
                return True
                
            except Exception as e:
                logger.warning(f"Navigation timeout or error: {e}")
                # Still might be successful, check URL
                new_url = page.url
                if new_url != self.captcha_page_url:
                    logger.info(f"✅ Navigation successful despite timeout. New URL: {new_url}")
                    return True
                else:
                    raise CaptchaTestError("Navigation did not occur after clicking Continue")
            
        except Exception as e:
            logger.error(f"❌ Error clicking Continue button: {e}")
            raise CaptchaTestError(f"Failed to click Continue button: {e}")
    
    async def run_test(self):
        """Main test execution"""
        logger.info("=" * 70)
        logger.info("🚀 STARTING ALTCHA CAPTCHA TEST")
        logger.info("=" * 70)
        
        async with async_playwright() as p:
            browser = None
            try:
                # Launch browser in visible mode
                logger.info("🌐 Launching browser...")
                browser = await p.chromium.launch(
                    headless=False,
                    slow_mo=50,  # 50ms delay for visibility
                    args=[
                        '--start-maximized',
                        '--auto-open-devtools-for-tabs'  # This opens devtools
                    ]
                )
                
                # Create context with realistic settings
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                    locale='en-US',
                    timezone_id='America/New_York'
                )
                
                page = await context.new_page()
                
                # Set up response interception
                page.on("response", self.response_handler)
                
                # Navigate to captcha page
                logger.info(f"🌐 Navigating to: {self.captcha_page_url}")
                await page.goto(self.captcha_page_url, wait_until="networkidle", timeout=30000)
                logger.info("✓ Page loaded successfully")
                
                # Human-like delay after page load (reading the page)
                await self.random_delay(1000, 2000)
                
                # Step 1: Click the checkbox
                logger.info("\n" + "─" * 70)
                logger.info("STEP 1: Clicking ALTCHA checkbox")
                logger.info("─" * 70)
                await self.find_and_click_checkbox(page)
                
                # Small delay after clicking
                await self.random_delay(300, 600)
                
                # Step 2: Wait for proof-of-work
                logger.info("\n" + "─" * 70)
                logger.info("STEP 2: Waiting for proof-of-work computation")
                logger.info("─" * 70)
                await self.wait_for_proof_of_work(page, timeout_ms=60000)
                
                # Step 3: Click Continue
                logger.info("\n" + "─" * 70)
                logger.info("STEP 3: Clicking Continue button")
                logger.info("─" * 70)
                await self.click_continue_button(page)
                
                # Success!
                logger.info("\n" + "=" * 70)
                logger.info("✅ CAPTCHA TEST COMPLETED SUCCESSFULLY!")
                logger.info("=" * 70)
                logger.info("\n📋 Test Summary:")
                logger.info("  ✓ Page loaded")
                logger.info("  ✓ Checkbox clicked")
                logger.info("  ✓ Proof-of-work verified")
                logger.info("  ✓ Continue button clicked")
                logger.info("  ✓ Navigation successful")
                logger.info("=" * 70 + "\n")
                
                # Keep browser open briefly to see final state
                await self.random_delay(2000, 3000)
                
                await browser.close()
                return True
                
            except CaptchaTestError as e:
                logger.error("\n" + "=" * 70)
                logger.error(f"❌ CAPTCHA TEST FAILED: {e}")
                logger.error("=" * 70 + "\n")
                # Keep browser open longer on error for inspection
                if browser:
                    logger.info("⏸️  Browser will remain open for 10 seconds for inspection...")
                    await asyncio.sleep(10)
                    await browser.close()
                return False
                
            except Exception as e:
                logger.error("\n" + "=" * 70)
                logger.error(f"❌ UNEXPECTED ERROR: {e}", exc_info=True)
                logger.error("=" * 70 + "\n")
                # Keep browser open longer on error for inspection
                if browser:
                    logger.info("⏸️  Browser will remain open for 10 seconds for inspection...")
                    await asyncio.sleep(10)
                    await browser.close()
                return False


async def solve_altcha(url, headless=True, user_agent=None):
    """Solve the ALTCHA captcha and return cookies for use with a requests session.

    Args:
        url: The URL of the page with the ALTCHA captcha.
        headless: Whether to run the browser in headless mode.
        user_agent: Browser user-agent string. Defaults to a Chrome UA.

    Returns:
        List of cookie dicts from the browser session.
    """
    tester = CaptchaTester(captcha_page_url=url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            slow_mo=50 if not headless else 0,
        )

        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='Europe/London',
        )

        page = await context.new_page()
        page.on("response", tester.response_handler)

        logger.info(f"Navigating to: {url}")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await tester.random_delay(1000, 2000)

        await tester.find_and_click_checkbox(page)
        await tester.random_delay(300, 600)
        await tester.wait_for_proof_of_work(page, timeout_ms=60000)

        label = await page.query_selector("altcha-widget .altcha-label")
        if label:
            label_text = await label.inner_text()
            logger.info(f"ALTCHA label text: '{label_text.strip()}'")

        await tester.click_continue_button(page)

        # Wait for cookies to be set after navigation
        for attempt in range(10):
            await asyncio.sleep(1)
            cookies = await context.cookies()
            if cookies:
                break
            logger.info(f"Waiting for cookies... (attempt {attempt + 1})")

        await browser.close()

        if not cookies:
            raise CaptchaTestError("No cookies received after solving ALTCHA")

        logger.info(f"ALTCHA solved, got {len(cookies)} cookies")
        return cookies


async def main():
    """Example usage"""

    # Configure your test parameters
    # CAPTCHA_PAGE_URL = "file:///Users/dread/jobadscrape/altcha.html"
    CAPTCHA_PAGE_URL = "https://www.civilservicejobs.service.gov.uk/csr/index.cgi"
    CHALLENGE_URL_PATTERN = "ProtectCaptcha=1"  # Matches the challengeurl parameter

    # Create and run the tester
    tester = CaptchaTester(
        captcha_page_url=CAPTCHA_PAGE_URL,
        challenge_url_pattern=CHALLENGE_URL_PATTERN
    )

    success = await tester.run_test()

    if success:
        logger.info("\n🎉 TEST PASSED ✓\n")
        return 0
    else:
        logger.error("\n💥 TEST FAILED ✗\n")
        return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        datefmt='%H:%M',
    )
    exit_code = asyncio.run(main())
    exit(exit_code)
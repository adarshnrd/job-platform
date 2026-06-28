"""LinkedIn session adapter — capture, validate, Easy Apply."""

import httpx
from loguru import logger
from services.sessions.adapters.base import (
    BaseSessionAdapter,
    CapturedSession,
    ValidationResult,
    ApplicationResult,
)


class LinkedInAdapter(BaseSessionAdapter):
    platform_name = "linkedin"
    login_url = "https://www.linkedin.com/login"
    default_session_lifetime_days = 30
    display_name = "LinkedIn"
    icon = "linkedin"

    # URLs that indicate the user has logged in successfully
    _POST_LOGIN_PATTERNS = [
        "linkedin.com/feed",
        "linkedin.com/jobs",
        "linkedin.com/in/",
        "linkedin.com/mynetwork",
    ]
    # URLs that indicate an auth challenge (2FA, captcha, email verify)
    _CHALLENGE_PATTERNS = [
        "/checkpoint/",
        "/challenge/",
    ]

    async def is_login_complete(self, page) -> bool:
        url = page.url
        if any(p in url for p in self._CHALLENGE_PATTERNS):
            return False
        if "/login" in url or "/authwall" in url:
            return False
        return any(p in url for p in self._POST_LOGIN_PATTERNS)

    async def capture_session(self, page) -> CapturedSession:
        context = page.context
        cookies = await context.cookies()
        user_agent = await page.evaluate("navigator.userAgent")
        viewport = page.viewport_size

        # Try to extract LinkedIn profile info from the page
        platform_username = None
        platform_user_id = None
        try:
            platform_username = await page.evaluate("""
                () => {
                    const el = document.querySelector('.feed-identity-module__actor-meta a');
                    if (el) return el.href;
                    const nav = document.querySelector('a[href*="/in/"]');
                    if (nav) return nav.href;
                    return null;
                }
            """)
        except Exception:
            pass

        # Filter to LinkedIn-relevant cookies only
        linkedin_cookies = [
            c for c in cookies
            if "linkedin.com" in (c.get("domain", ""))
        ]

        return CapturedSession(
            cookies=linkedin_cookies or cookies,
            user_agent=user_agent,
            viewport=viewport or {"width": 1920, "height": 1080},
            platform_username=platform_username,
            platform_user_id=platform_user_id,
        )

    async def validate_cookies(self, cookies: list[dict], metadata: dict) -> ValidationResult:
        """Check if LinkedIn session is still alive by hitting the feed.
        If we get redirected to /login, the session is dead.
        """
        cookie_header = "; ".join(
            f"{c['name']}={c['value']}" for c in cookies
            if "linkedin.com" in c.get("domain", "")
        )
        if not cookie_header:
            return ValidationResult(valid=False, reason="No LinkedIn cookies found", is_auth_failure=True)

        headers = {
            "cookie": cookie_header,
            "user-agent": metadata.get("user_agent", "Mozilla/5.0"),
        }

        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
                resp = await client.get("https://www.linkedin.com/feed/", headers=headers)

            if resp.status_code == 200:
                return ValidationResult(valid=True, reason="Feed accessible")

            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                if "/login" in location or "/authwall" in location:
                    return ValidationResult(
                        valid=False,
                        reason="Redirected to login — session expired",
                        is_auth_failure=True,
                    )
                return ValidationResult(valid=True, reason=f"Redirect to {location[:100]}")

            if resp.status_code == 429:
                return ValidationResult(valid=True, reason="Rate limited (session likely valid)")

            return ValidationResult(
                valid=False,
                reason=f"Unexpected status {resp.status_code}",
                is_auth_failure=resp.status_code in (401, 403),
            )

        except Exception as e:
            return ValidationResult(valid=False, reason=f"Validation request failed: {e}")

    async def apply_to_job(
        self,
        browser_context,
        application: dict,
        form_data: dict,
        resume_path: str | None = None,
        cover_letter: str | None = None,
        screening_answerer=None,
    ) -> ApplicationResult:
        """Submit a LinkedIn Easy Apply application.

        Steps:
        1. Navigate to job page
        2. Click Easy Apply button
        3. Walk multi-step form (contact, resume, screening questions)
        4. Submit
        5. Capture confirmation
        """
        page = await browser_context.new_page()
        apply_url = application.get("apply_url") or application.get("source_url")

        try:
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Check if already applied to this job
            already_applied = page.locator(
                'span:has-text("Applied"), '
                'button:has-text("Applied"), '
                'li-icon[type="success-pebble-icon"]'
            ).first
            try:
                if await already_applied.is_visible(timeout=2000):
                    logger.info(f"LinkedIn: already applied to {apply_url}")
                    return ApplicationResult(
                        success=True,
                        metadata={
                            "already_applied": True,
                            "applied_url": apply_url,
                            "note": "Application was previously submitted",
                        },
                    )
            except Exception:
                pass

            # Check if it's an Easy Apply job
            easy_apply_btn = page.locator(
                'button:has-text("Easy Apply"), '
                'button.jobs-apply-button'
            ).first
            if not await easy_apply_btn.is_visible(timeout=5000):
                return ApplicationResult(
                    success=False,
                    error="No Easy Apply button found — job may require external application",
                )

            await easy_apply_btn.click()
            await page.wait_for_timeout(1500)

            # Walk through multi-step form
            max_steps = 10
            for step in range(max_steps):
                # Fill visible input fields
                await self._fill_form_fields(page, form_data)

                # Upload resume if file input visible
                if resume_path:
                    file_input = page.locator('input[type="file"]').first
                    if await file_input.count() > 0:
                        try:
                            await file_input.set_input_files(resume_path)
                            await page.wait_for_timeout(1000)
                        except Exception:
                            pass

                # Handle screening questions
                await self._answer_screening_questions(page, screening_answerer)

                # Check for Submit button (final step)
                submit_btn = page.locator(
                    'button:has-text("Submit application"), '
                    'button[aria-label="Submit application"]'
                ).first
                if await submit_btn.is_visible(timeout=1000):
                    await submit_btn.click()
                    await page.wait_for_timeout(2000)

                    # Check for confirmation
                    confirmation = page.locator(
                        'h2:has-text("Application sent"), '
                        'div:has-text("Your application was sent")'
                    ).first
                    if await confirmation.is_visible(timeout=5000):
                        return ApplicationResult(
                            success=True,
                            metadata={
                                "step": "submitted",
                                "applied_url": apply_url,
                            },
                        )
                    return ApplicationResult(
                        success=True,
                        metadata={
                            "step": "submitted_no_confirmation",
                            "applied_url": apply_url,
                        },
                    )

                # Click Next button for multi-step forms
                next_btn = page.locator(
                    'button:has-text("Next"), '
                    'button:has-text("Continue"), '
                    'button:has-text("Review")'
                ).first
                if await next_btn.is_visible(timeout=1000):
                    await next_btn.click()
                    await page.wait_for_timeout(1500)
                else:
                    break

            return ApplicationResult(
                success=False,
                error="Could not complete the multi-step form",
            )

        except Exception as e:
            is_auth = "login" in str(e).lower() or "401" in str(e)
            return ApplicationResult(
                success=False,
                error=str(e)[:500],
                is_auth_failure=is_auth,
            )
        finally:
            await page.close()

    async def _fill_form_fields(self, page, form_data: dict) -> None:
        """Fill standard form fields on the current step."""
        field_map = {
            'input[name="firstName"], input[id*="firstName"]': form_data.get("full_name", "").split()[0] if form_data.get("full_name") else "",
            'input[name="lastName"], input[id*="lastName"]': " ".join(form_data.get("full_name", "").split()[1:]) if form_data.get("full_name") else "",
            'input[name="email"], input[id*="email"], input[type="email"]': form_data.get("email", ""),
            'input[name="phone"], input[id*="phone"], input[type="tel"]': form_data.get("phone", ""),
            'input[name="location"], input[id*="city"]': form_data.get("location", ""),
        }
        for selector, value in field_map.items():
            if not value:
                continue
            try:
                field = page.locator(selector).first
                if await field.is_visible(timeout=500):
                    current = await field.input_value()
                    if not current:
                        await field.fill(value)
            except Exception:
                pass

    async def _answer_screening_questions(self, page, screening_answerer) -> None:
        """Detect and answer screening questions on the current step."""
        if not screening_answerer:
            return

        try:
            question_groups = page.locator(
                '.jobs-easy-apply-form-section__grouping, '
                'div[data-test-form-element]'
            )
            count = await question_groups.count()

            for i in range(count):
                group = question_groups.nth(i)
                label_el = group.locator('label, span.fb-form-element-label').first
                if not await label_el.is_visible(timeout=300):
                    continue
                question_text = (await label_el.text_content() or "").strip()
                if not question_text:
                    continue

                # Check for text input
                text_input = group.locator('input[type="text"], textarea').first
                if await text_input.is_visible(timeout=300):
                    current_value = await text_input.input_value()
                    if not current_value:
                        try:
                            answer = screening_answerer(question_text)
                            if answer and "[NEEDS_INFO]" not in answer:
                                await text_input.fill(answer)
                        except Exception:
                            pass

                # Check for select dropdown
                select_el = group.locator('select').first
                if await select_el.is_visible(timeout=300):
                    try:
                        options = await select_el.locator('option').all_text_contents()
                        if len(options) > 1:
                            answer = screening_answerer(question_text)
                            best_match = self._find_best_option(answer, options)
                            if best_match:
                                await select_el.select_option(label=best_match)
                    except Exception:
                        pass

        except Exception:
            pass

    @staticmethod
    def _find_best_option(answer: str, options: list[str]) -> str | None:
        """Find the dropdown option that best matches the AI's answer."""
        if not answer or not options:
            return None
        answer_lower = answer.lower()
        for opt in options:
            if opt.strip().lower() in answer_lower or answer_lower in opt.strip().lower():
                return opt.strip()
        non_empty = [o.strip() for o in options if o.strip() and o.strip().lower() not in ("select", "select an option", "--")]
        return non_empty[0] if non_empty else None

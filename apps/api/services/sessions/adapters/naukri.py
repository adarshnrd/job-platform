"""Naukri session adapter — capture, validate, apply."""

import httpx
from loguru import logger
from services.sessions.adapters.base import (
    BaseSessionAdapter,
    CapturedSession,
    ValidationResult,
    ApplicationResult,
)


class NaukriAdapter(BaseSessionAdapter):
    platform_name = "naukri"
    login_url = "https://www.naukri.com/nlogin/login"
    default_session_lifetime_days = 14
    display_name = "Naukri"
    icon = "naukri"

    _POST_LOGIN_PATTERNS = [
        "naukri.com/mnjuser",
        "naukri.com/dashboard",
        "naukri.com/nlogin/homepage",
    ]

    async def is_login_complete(self, page) -> bool:
        url = page.url
        if "/nlogin/login" in url or "/nlogin/register" in url:
            return False
        return any(p in url for p in self._POST_LOGIN_PATTERNS)

    async def capture_session(self, page) -> CapturedSession:
        context = page.context
        cookies = await context.cookies()
        user_agent = await page.evaluate("navigator.userAgent")
        viewport = page.viewport_size

        platform_username = None
        try:
            platform_username = await page.evaluate("""
                () => {
                    const el = document.querySelector('.nI-gNb-drawer__avatar-name, .user-name');
                    return el ? el.textContent.trim() : null;
                }
            """)
        except Exception:
            pass

        naukri_cookies = [
            c for c in cookies
            if "naukri.com" in (c.get("domain", ""))
        ]

        return CapturedSession(
            cookies=naukri_cookies or cookies,
            user_agent=user_agent,
            viewport=viewport or {"width": 1920, "height": 1080},
            platform_username=platform_username,
        )

    async def validate_cookies(self, cookies: list[dict], metadata: dict) -> ValidationResult:
        """Check if Naukri session is alive by hitting the profile page."""
        cookie_header = "; ".join(
            f"{c['name']}={c['value']}" for c in cookies
            if "naukri.com" in c.get("domain", "")
        )
        if not cookie_header:
            return ValidationResult(valid=False, reason="No Naukri cookies found", is_auth_failure=True)

        headers = {
            "cookie": cookie_header,
            "user-agent": metadata.get("user_agent", "Mozilla/5.0"),
        }

        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
                resp = await client.get("https://www.naukri.com/mnjuser/profile", headers=headers)

            if resp.status_code == 200:
                body = resp.text[:500]
                if "login" in body.lower() and "profile" not in body.lower():
                    return ValidationResult(valid=False, reason="Profile page shows login form", is_auth_failure=True)
                return ValidationResult(valid=True, reason="Profile page accessible")

            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                if "login" in location.lower():
                    return ValidationResult(valid=False, reason="Redirected to login", is_auth_failure=True)
                return ValidationResult(valid=True, reason=f"Redirect to {location[:100]}")

            return ValidationResult(
                valid=False,
                reason=f"Unexpected status {resp.status_code}",
                is_auth_failure=resp.status_code in (401, 403),
            )

        except Exception as e:
            return ValidationResult(valid=False, reason=f"Validation failed: {e}")

    async def apply_to_job(
        self,
        browser_context,
        application: dict,
        form_data: dict,
        resume_path: str | None = None,
        cover_letter: str | None = None,
        screening_answerer=None,
    ) -> ApplicationResult:
        """Submit a Naukri application.

        Naukri's apply flow is simpler than LinkedIn — typically a single
        "Apply" button click (resume is already on profile).
        """
        page = await browser_context.new_page()
        apply_url = application.get("apply_url") or application.get("source_url")

        try:
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Look for Apply button
            apply_btn = page.locator(
                'button:has-text("Apply"), '
                'a:has-text("Apply on company site"), '
                'button.apply-button, '
                'button[id*="apply"]'
            ).first

            if not await apply_btn.is_visible(timeout=5000):
                already_applied = page.locator('span:has-text("Already Applied"), div:has-text("Already Applied")').first
                if await already_applied.is_visible(timeout=1000):
                    return ApplicationResult(
                        success=True,
                        metadata={
                            "already_applied": True,
                            "applied_url": apply_url,
                            "note": "Already applied to this job",
                        },
                    )
                return ApplicationResult(success=False, error="No Apply button found")

            await apply_btn.click()
            await page.wait_for_timeout(2000)

            # Handle post-click scenarios

            # Scenario 1: Direct application (no form)
            success_toast = page.locator(
                'div:has-text("applied successfully"), '
                'div:has-text("Application Submitted"), '
                'span:has-text("applied")'
            ).first
            if await success_toast.is_visible(timeout=3000):
                return ApplicationResult(
                    success=True,
                    metadata={"method": "direct_apply", "applied_url": apply_url},
                )

            # Scenario 2: Application form appeared
            form = page.locator('form, div.apply-form, div[class*="chatbot"]').first
            if await form.is_visible(timeout=2000):
                await self._fill_naukri_form(page, form_data, screening_answerer)

                submit_btn = page.locator(
                    'button:has-text("Submit"), '
                    'button:has-text("Apply"), '
                    'input[type="submit"]'
                ).first
                if await submit_btn.is_visible(timeout=2000):
                    await submit_btn.click()
                    await page.wait_for_timeout(2000)

                    if await success_toast.is_visible(timeout=5000):
                        return ApplicationResult(
                            success=True,
                            metadata={"method": "form_submit", "applied_url": apply_url},
                        )

            # Scenario 3: Redirected to external site
            if "naukri.com" not in page.url:
                return ApplicationResult(
                    success=False,
                    error="Redirected to external company portal — cannot auto-apply",
                    metadata={"redirect_url": page.url},
                )

            return ApplicationResult(
                success=False,
                error="Could not confirm application submission",
            )

        except Exception as e:
            is_auth = "login" in str(e).lower() or "unauthorized" in str(e).lower()
            return ApplicationResult(
                success=False,
                error=str(e)[:500],
                is_auth_failure=is_auth,
            )
        finally:
            await page.close()

    async def _fill_naukri_form(self, page, form_data: dict, screening_answerer) -> None:
        """Fill Naukri's application form fields."""
        field_map = {
            'input[name*="name"], input[placeholder*="name"]': form_data.get("full_name", ""),
            'input[name*="email"], input[type="email"]': form_data.get("email", ""),
            'input[name*="phone"], input[name*="mobile"], input[type="tel"]': form_data.get("phone", ""),
            'input[name*="experience"], input[placeholder*="experience"]': str(form_data.get("years_experience", "")),
            'input[name*="salary"], input[placeholder*="salary"]': str(form_data.get("expected_salary_min", "")),
            'input[name*="notice"], input[placeholder*="notice"]': str(form_data.get("notice_period_days", "")),
            'input[name*="location"], input[placeholder*="location"]': form_data.get("location", ""),
        }

        for selector, value in field_map.items():
            if not value:
                continue
            try:
                field = page.locator(selector).first
                if await field.is_visible(timeout=500):
                    current = await field.input_value()
                    if not current:
                        await field.fill(str(value))
            except Exception:
                pass

        # Handle screening questions via textareas
        if screening_answerer:
            try:
                textareas = page.locator("textarea")
                count = await textareas.count()
                for i in range(count):
                    ta = textareas.nth(i)
                    if not await ta.is_visible(timeout=300):
                        continue
                    label = await ta.get_attribute("placeholder") or ""
                    if not label:
                        label_el = page.locator(f"label[for='{await ta.get_attribute('id') or ''}']").first
                        if await label_el.is_visible(timeout=300):
                            label = await label_el.text_content() or ""
                    if label.strip():
                        current = await ta.input_value()
                        if not current:
                            try:
                                answer = screening_answerer(label.strip())
                                if answer and "[NEEDS_INFO]" not in answer:
                                    await ta.fill(answer)
                            except Exception:
                                pass
            except Exception:
                pass

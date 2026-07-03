"""
SimpleApplyAdapter — shared base for authenticated "1-click apply" job boards.

Several Indian portals (Instahyre, Foundit, Hirist, iimjobs, Shine, TimesJobs)
share the same shape: the user logs in once, the resume lives on their profile,
and applying is a single button click that may pop a small questionnaire. This
base captures that flow so each portal is just a few lines of configuration.

Subclasses set the class attributes; they only override methods for genuinely
portal-specific behavior (e.g. Cutshort pausing on assessments).
"""
from __future__ import annotations

import httpx
from loguru import logger

from services.sessions.adapters.base import (
    BaseSessionAdapter,
    CapturedSession,
    ValidationResult,
    ApplicationResult,
)
from services.questions.schema import NEEDS_INFO_TOKEN


class SimpleApplyAdapter(BaseSessionAdapter):
    # ── Per-portal configuration (override in subclasses) ──
    cookie_domain: str = ""                 # e.g. "instahyre.com"
    post_login_patterns: list[str] = []     # URL fragments that mean "logged in"
    login_markers: list[str] = ["/login", "/signin", "/register"]
    validate_url: str = ""                  # an authenticated page to probe
    validate_login_hint: str = "login"     # text/redirect that means "logged out"
    apply_button_selectors: list[str] = [
        'button:has-text("Apply")',
        'a:has-text("Apply")',
        'button[class*="apply"]',
        'button[id*="apply"]',
    ]
    success_selectors: list[str] = [
        'div:has-text("applied successfully")',
        'div:has-text("Application submitted")',
        'span:has-text("Applied")',
        'div:has-text("successfully applied")',
    ]
    already_applied_selectors: list[str] = [
        'span:has-text("Already Applied")',
        'button:has-text("Applied")',
        'div:has-text("You have already applied")',
    ]

    # ── Login lifecycle ──
    async def is_login_complete(self, page) -> bool:
        url = page.url
        if any(m in url for m in self.login_markers):
            return False
        if self.post_login_patterns:
            return any(p in url for p in self.post_login_patterns)
        # Fallback: any same-domain page that isn't the login page.
        return self.cookie_domain in url

    async def capture_session(self, page) -> CapturedSession:
        context = page.context
        cookies = await context.cookies()
        user_agent = await page.evaluate("navigator.userAgent")
        viewport = page.viewport_size
        domain_cookies = [c for c in cookies if self.cookie_domain in (c.get("domain", ""))]
        return CapturedSession(
            cookies=domain_cookies or cookies,
            user_agent=user_agent,
            viewport=viewport or {"width": 1920, "height": 1080},
        )

    async def validate_cookies(self, cookies: list[dict], metadata: dict) -> ValidationResult:
        cookie_header = "; ".join(
            f"{c['name']}={c['value']}" for c in cookies
            if self.cookie_domain in c.get("domain", "")
        )
        if not cookie_header:
            return ValidationResult(valid=False, reason=f"No {self.platform_name} cookies", is_auth_failure=True)
        if not self.validate_url:
            # No probe configured — trust presence of cookies.
            return ValidationResult(valid=True, reason="Cookies present")

        headers = {"cookie": cookie_header, "user-agent": metadata.get("user_agent", "Mozilla/5.0")}
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
                resp = await client.get(self.validate_url, headers=headers)
            if resp.status_code == 200:
                if self.validate_login_hint in resp.text[:2000].lower():
                    return ValidationResult(valid=False, reason="Page shows login", is_auth_failure=True)
                return ValidationResult(valid=True, reason="Authenticated page accessible")
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location", "").lower()
                if any(m.strip("/") in loc for m in self.login_markers):
                    return ValidationResult(valid=False, reason="Redirected to login", is_auth_failure=True)
                return ValidationResult(valid=True, reason=f"Redirect to {loc[:80]}")
            return ValidationResult(
                valid=False, reason=f"Unexpected status {resp.status_code}",
                is_auth_failure=resp.status_code in (401, 403),
            )
        except Exception as e:
            return ValidationResult(valid=False, reason=f"Validation failed: {e}")

    # ── Apply flow ──
    async def apply_to_job(
        self,
        browser_context,
        application: dict,
        form_data: dict,
        resume_path: str | None = None,
        cover_letter: str | None = None,
        screening_answerer=None,
    ) -> ApplicationResult:
        page = await browser_context.new_page()
        apply_url = application.get("apply_url") or application.get("source_url")
        try:
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Portal-specific guard (e.g. Cutshort assessment) — pause, don't apply.
            block = await self._pre_apply_block(page)
            if block:
                return ApplicationResult(success=False, error=block,
                                         metadata={"needs_manual": True})

            # Already applied?
            if await self._any_visible(page, self.already_applied_selectors, timeout=1500):
                return ApplicationResult(success=True, metadata={
                    "already_applied": True, "applied_url": apply_url,
                })

            apply_btn = page.locator(", ".join(self.apply_button_selectors)).first
            if not await apply_btn.is_visible(timeout=5000):
                return ApplicationResult(success=False,
                                         error="No Apply button found — may require external application")
            await apply_btn.click()
            await page.wait_for_timeout(2000)

            # Direct success?
            if await self._any_visible(page, self.success_selectors, timeout=3000):
                return ApplicationResult(success=True, metadata={"method": "direct", "applied_url": apply_url})

            # A questionnaire appeared — fill via the resolver.
            filled_ok = await self._fill_questionnaire(page, form_data, screening_answerer)
            if not filled_ok:
                # A required question was unknown → resolver recorded it as pending.
                # Report failure so the bot's pause path takes over.
                return ApplicationResult(success=False,
                                         error="Application paused — question needs your input",
                                         metadata={"needs_input": True})

            submit = page.locator(
                'button:has-text("Submit"), button:has-text("Apply"), input[type="submit"]'
            ).first
            if await submit.is_visible(timeout=2000):
                await submit.click()
                await page.wait_for_timeout(2000)
                if await self._any_visible(page, self.success_selectors, timeout=5000):
                    return ApplicationResult(success=True, metadata={"method": "form", "applied_url": apply_url})

            if self.cookie_domain not in page.url:
                return ApplicationResult(success=False,
                                         error="Redirected to external portal — cannot auto-apply",
                                         metadata={"redirect_url": page.url})
            return ApplicationResult(success=False, error="Could not confirm submission")
        except Exception as e:
            is_auth = any(w in str(e).lower() for w in ("login", "unauthorized", "401", "403"))
            return ApplicationResult(success=False, error=str(e)[:500], is_auth_failure=is_auth)
        finally:
            await page.close()

    # ── Hooks / helpers ──
    async def _pre_apply_block(self, page) -> str | None:
        """Return a reason string to abort before applying, or None to proceed.
        Overridden by portals that must never auto-submit certain flows."""
        return None

    async def _fill_questionnaire(self, page, form_data: dict, screening_answerer) -> bool:
        """Fill standard fields + resolve questions. Returns False if a required
        question was left unanswered (resolver returned the NEEDS_INFO sentinel)."""
        # Standard identity fields.
        field_map = {
            'input[name*="name"], input[placeholder*="name" i]': form_data.get("full_name", ""),
            'input[type="email"], input[name*="email" i]': form_data.get("email", ""),
            'input[type="tel"], input[name*="phone" i], input[name*="mobile" i]': form_data.get("phone", ""),
            'input[name*="location" i], input[placeholder*="location" i]': form_data.get("location", ""),
        }
        for selector, value in field_map.items():
            if not value:
                continue
            try:
                fld = page.locator(selector).first
                if await fld.is_visible(timeout=400) and not await fld.input_value():
                    await fld.fill(str(value))
            except Exception:
                pass

        if not screening_answerer:
            return True

        all_answered = True
        # Text inputs / textareas with an associated label.
        try:
            fields = page.locator('textarea, input[type="text"]')
            count = await fields.count()
            for i in range(count):
                fld = fields.nth(i)
                if not await fld.is_visible(timeout=200):
                    continue
                if await fld.input_value():
                    continue
                label = await self._label_for(page, fld)
                if not label:
                    continue
                answer = screening_answerer(label)
                if answer and NEEDS_INFO_TOKEN not in answer:
                    await fld.fill(answer)
                else:
                    all_answered = False
        except Exception:
            pass

        # Selects.
        try:
            selects = page.locator("select")
            for i in range(await selects.count()):
                sel = selects.nth(i)
                if not await sel.is_visible(timeout=200):
                    continue
                label = await self._label_for(page, sel)
                if not label:
                    continue
                answer = screening_answerer(label)
                if not answer or NEEDS_INFO_TOKEN in answer:
                    all_answered = False
                    continue
                try:
                    options = await sel.locator("option").all_text_contents()
                    match = self._best_option(answer, options)
                    if match:
                        await sel.select_option(label=match)
                except Exception:
                    pass
        except Exception:
            pass

        return all_answered

    @staticmethod
    async def _label_for(page, field) -> str:
        """Best-effort label text for a field via placeholder / aria / <label for>."""
        try:
            for attr in ("aria-label", "placeholder", "name"):
                v = await field.get_attribute(attr)
                if v and v.strip():
                    return v.strip()
            fid = await field.get_attribute("id")
            if fid:
                lbl = page.locator(f"label[for='{fid}']").first
                if await lbl.is_visible(timeout=200):
                    txt = await lbl.text_content()
                    if txt and txt.strip():
                        return txt.strip()
        except Exception:
            pass
        return ""

    @staticmethod
    async def _any_visible(page, selectors: list[str], timeout: int = 1000) -> bool:
        for sel in selectors:
            try:
                if await page.locator(sel).first.is_visible(timeout=timeout):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _best_option(answer: str, options: list[str]) -> str | None:
        if not answer or not options:
            return None
        al = answer.lower()
        for opt in options:
            o = opt.strip().lower()
            if o and (o in al or al in o):
                return opt.strip()
        return None

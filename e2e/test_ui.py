"""End-to-end UI tests: drive the web UI in headless Chromium against a running API.

Requires a running app with SEED_DEMO_DATA=true on a fresh database.
    BASE_URL=http://localhost:8000 pytest e2e -q
Screenshots are written to e2e/screenshots/.
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect, sync_playwright

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
SHOTS = Path(__file__).parent / "screenshots"
SHOTS.mkdir(exist_ok=True)


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
        pg = ctx.new_page()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        yield pg
        assert errors == [], f"JavaScript errors on page: {errors}"
        browser.close()


def shot(page: Page, name: str) -> None:
    page.screenshot(path=SHOTS / f"{name}.png", full_page=True)


def submit_move(page: Page, tab: str, amount: str, description: str = "") -> None:
    page.locator(f".tabs button[data-tab={tab}]").click()
    page.fill("#move input[name=amount]", amount)
    page.fill("#move input[name=description]", description)
    page.click("#move-submit")


def selected_balance(page: Page):
    return page.locator(".acct.selected [data-testid=balance]")


def test_01_loads_with_healthy_status_and_seeded_customers(page: Page):
    page.goto(BASE_URL + "/")  # root redirects to /ui
    expect(page).to_have_url(re.compile(r"/ui$"))
    expect(page.get_by_test_id("health")).to_contain_text("healthy")
    expect(page.get_by_test_id("health")).to_contain_text("db ok")
    expect(page.locator("#customers li")).to_have_count(3)
    expect(page.locator("#customers li.selected")).to_contain_text("Test Customer Alpha")
    expect(page.locator(".acct [data-testid=balance]").first).to_have_text("$2,500.00")
    shot(page, "01-loaded")


def test_02_create_customer(page: Page):
    page.fill("#new-customer input[name=full_name]", "UI Test Customer")
    page.fill("#new-customer input[name=email]", "ui.test@example.com")
    page.click("#new-customer button")
    expect(page.locator(".toast.ok").last).to_contain_text("UI Test Customer")
    expect(page.locator("#customers li")).to_have_count(4)
    expect(page.locator("#customers li.selected")).to_contain_text("UI Test Customer")


def test_03_duplicate_email_shows_error(page: Page):
    page.fill("#new-customer input[name=full_name]", "Someone Else")
    page.fill("#new-customer input[name=email]", "ui.test@example.com")
    page.click("#new-customer button")
    expect(page.locator(".toast.bad").last).to_contain_text("409")
    expect(page.locator(".toast.bad").last).to_contain_text("email already registered")
    expect(page.locator("#customers li")).to_have_count(4)


def test_04_open_account(page: Page):
    page.click("#open-account")
    expect(page.locator(".toast.ok").last).to_contain_text("opened")
    expect(page.locator(".acct")).to_have_count(1)
    expect(selected_balance(page)).to_have_text("$0.00")
    expect(page.locator("#tx-empty")).to_have_text("No transactions yet.")


def test_05_deposit(page: Page):
    submit_move(page, "deposit", "500", "salary")
    expect(selected_balance(page)).to_have_text("$500.00")
    expect(page.locator("#tx-body tr")).to_have_count(1)
    expect(page.locator("#tx-body tr").first).to_contain_text("deposit")


def test_06_withdraw(page: Page):
    submit_move(page, "withdrawal", "120.50", "groceries")
    expect(selected_balance(page)).to_have_text("$379.50")
    expect(page.locator("#tx-body tr").first).to_contain_text("withdrawal")


def test_07_overdraft_rejected(page: Page):
    submit_move(page, "withdrawal", "10000")
    expect(page.locator(".toast.bad").last).to_contain_text("insufficient funds")
    expect(selected_balance(page)).to_have_text("$379.50")
    expect(page.locator("#tx-body tr")).to_have_count(2)
    shot(page, "07-overdraft-rejected")


def test_08_invalid_amount_blocked(page: Page):
    submit_move(page, "deposit", "1.234")  # 3 decimals fails the input pattern
    assert page.locator("#move input[name=amount]").evaluate("e => !e.validity.valid")
    expect(selected_balance(page)).to_have_text("$379.50")


def test_09_transfer_to_other_customer(page: Page):
    page.locator(".tabs button[data-tab=transfer]").click()
    target = page.locator("#move select[name=to_account_id] option", has_text="Test Customer Alpha")
    page.select_option("#move select[name=to_account_id]", value=target.get_attribute("value"))
    page.fill("#move input[name=amount]", "79.50")
    page.fill("#move input[name=description]", "rent share")
    page.click("#move-submit")
    expect(page.locator(".toast.ok").last).to_contain_text("Transferred 79.50")
    expect(selected_balance(page)).to_have_text("$300.00")
    expect(page.locator("#tx-body tr")).to_have_count(3)
    expect(page.locator("#tx-body tr").first).to_contain_text("transfer out")
    shot(page, "09-after-transfer")


def test_10_recipient_balance_and_history(page: Page):
    page.locator("#customers li", has_text="Test Customer Alpha").click()
    # first account is auto-selected when a customer is picked
    expect(selected_balance(page)).to_have_text("$2,579.50")
    expect(page.locator("#tx-body tr").first).to_contain_text("transfer in")
    expect(page.locator("#tx-body tr").first).to_contain_text("+$79.50")
    shot(page, "10-recipient")


def test_11_mobile_layout(page: Page):
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()
    expect(page.locator("#customers li")).to_have_count(4)
    scroll_w = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_w <= 390, f"horizontal overflow on mobile: {scroll_w}px"
    # account auto-selected, deposit tab active, transfer-only field hidden
    expect(selected_balance(page)).to_have_text("$2,579.50")
    expect(page.locator("#to-wrap")).to_be_hidden()
    expect(page.locator("#move-submit")).to_be_enabled()
    shot(page, "11-mobile")

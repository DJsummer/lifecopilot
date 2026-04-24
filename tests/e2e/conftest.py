"""
端到端 Selenium 测试配置与 fixtures
需要：
1. 运行中的前端（微信小程序 H5/Web 管理后台）
2. Chrome + ChromeDriver（由 webdriver-manager 自动管理）

使用方式：
  pytest tests/e2e/ -m e2e --base-url http://localhost:3000
"""
import os

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def pytest_addoption(parser):
    parser.addoption(
        "--base-url",
        action="store",
        default=os.getenv("E2E_BASE_URL", "http://localhost:3000"),
        help="前端 Web 地址（如 http://localhost:3000）",
    )
    parser.addoption(
        "--headless",
        action="store_true",
        default=os.getenv("E2E_HEADLESS", "true").lower() == "true",
        help="是否无头模式运行（CI 环境建议开启）",
    )


@pytest.fixture(scope="session")
def base_url(request) -> str:
    return request.config.getoption("--base-url")


@pytest.fixture(scope="session")
def driver(request):
    """
    Chrome WebDriver fixture
    - scope=session：整个测试 session 共用一个浏览器实例，节省启动时间
    - 测试结束后自动关闭
    """
    headless = request.config.getoption("--headless")
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,900")
    options.add_argument("--disable-gpu")

    service = Service(ChromeDriverManager().install())
    _driver = webdriver.Chrome(service=service, options=options)
    _driver.implicitly_wait(10)

    yield _driver

    _driver.quit()


@pytest.fixture
def page(driver, base_url: str):
    """每个测试前清空 cookies，回到初始状态"""
    driver.delete_all_cookies()
    driver.get(base_url)
    return driver

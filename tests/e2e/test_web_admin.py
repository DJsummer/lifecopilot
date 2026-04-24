"""
端到端 Selenium 测试：Web 管理后台
测试登录流程（占位，待前端实现后补充选择器）
"""
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


@pytest.mark.e2e
class TestWebAdminLogin:
    """
    Web 管理后台登录测试
    前提：Web 管理后台运行于 --base-url，且后端 API 可达
    """

    def test_login_page_loads(self, page, base_url: str):
        """登录页能正常加载"""
        page.get(f"{base_url}/login")
        wait = WebDriverWait(page, 10)
        # 等待邮箱输入框出现（选择器待前端实现后调整）
        email_input = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='email']"))
        )
        assert email_input.is_displayed()

    def test_login_with_valid_credentials(self, page, base_url: str):
        """
        有效凭据登录后跳转至 Dashboard
        注意：需要预先在测试数据库创建账户，或对接后端 register API
        """
        page.get(f"{base_url}/login")
        wait = WebDriverWait(page, 10)

        email_input = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='email']"))
        )
        password_input = page.find_element(By.CSS_SELECTOR, "input[type='password'], input[name='password']")
        submit_btn = page.find_element(By.CSS_SELECTOR, "button[type='submit']")

        email_input.clear()
        email_input.send_keys("admin@test.com")
        password_input.clear()
        password_input.send_keys("Test1234")
        submit_btn.click()

        # 登录成功后应跳转到 dashboard
        wait.until(EC.url_contains("/dashboard"))
        assert "/dashboard" in page.current_url

    def test_login_with_invalid_credentials(self, page, base_url: str):
        """错误密码应显示错误提示"""
        page.get(f"{base_url}/login")
        wait = WebDriverWait(page, 10)

        email_input = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='email']"))
        )
        password_input = page.find_element(By.CSS_SELECTOR, "input[type='password'], input[name='password']")
        submit_btn = page.find_element(By.CSS_SELECTOR, "button[type='submit']")

        email_input.send_keys("admin@test.com")
        password_input.send_keys("WrongPass999")
        submit_btn.click()

        # 应显示错误信息
        error_msg = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".error-message, [role='alert'], .ant-message-error")
            )
        )
        assert error_msg.is_displayed()

    def test_login_empty_fields_validation(self, page, base_url: str):
        """空表单提交应触发前端必填校验"""
        page.get(f"{base_url}/login")
        wait = WebDriverWait(page, 10)

        submit_btn = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "button[type='submit']"))
        )
        submit_btn.click()

        # 应有必填提示
        validation_msg = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".ant-form-item-explain-error, [class*='error'], [class*='required']")
            )
        )
        assert validation_msg.is_displayed()


@pytest.mark.e2e
class TestWebAdminDashboard:
    """
    Dashboard 页面测试（需登录状态）
    """

    @pytest.fixture(autouse=True)
    def login(self, page, base_url: str):
        """每个测试前自动登录"""
        page.get(f"{base_url}/login")
        wait = WebDriverWait(page, 10)
        email = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']")))
        pwd = page.find_element(By.CSS_SELECTOR, "input[type='password']")
        btn = page.find_element(By.CSS_SELECTOR, "button[type='submit']")
        email.send_keys("admin@test.com")
        pwd.send_keys("Test1234")
        btn.click()
        wait.until(EC.url_contains("/dashboard"))

    def test_dashboard_shows_family_members(self, page):
        """Dashboard 应展示家庭成员卡片"""
        wait = WebDriverWait(page, 10)
        member_cards = wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "[class*='member-card'], [data-testid='member-card']")
            )
        )
        assert len(member_cards) >= 1

    def test_dashboard_has_health_overview(self, page):
        """Dashboard 应有健康概览区域"""
        wait = WebDriverWait(page, 10)
        overview = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[class*='health-overview'], [data-testid='health-overview']")
            )
        )
        assert overview.is_displayed()

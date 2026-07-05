from playwright.async_api import async_playwright

class BrowserManager:
    def __init__(self, log_callback):
        self.log = log_callback  # 传入回调函数，避免直接依赖 PyQt Signal
        self.playwright = None
        self.browser = None

    async def connect(self):
        self.log(">>> 初始化 Playwright 连接...")
        await self.close() # 确保之前的被关闭
        try:
            self.playwright = await async_playwright().start()
            # 连接现有的 CDP
            self.browser = await self.playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
            self.log(">>> 已连接.")
            return True
        except Exception as e:
            self.log(f"连接失败: {str(e)}")
            await self.close()
            return False

    async def get_all_pages(self):
        if not self.browser or not self.browser.contexts:
            return []
        return self.browser.contexts[0].pages

    async def close(self):
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

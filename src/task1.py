import AI_analyse_V1 as analyser
import os, json, time
import pyperclip
import base64
import threading
import asyncio
from playwright.async_api import Page

class QualityCheckStep1():
    """初审审题逻辑"""

    def __init__(self, log_callback, result_callback, input_num_for_AI: str, stop_signal: threading.Event):    
        self.log = log_callback
        self.result = result_callback
        self.stop = stop_signal
        self.analyser = analyser.AsyncAnalyser()
        self._user_input = input_num_for_AI
        self.page_1: Page = None
        self.page_2: Page = None

        self.input_dataset: dict = {}
        self.output_dataset: dict = {}

    def sys_instruct_AI(self):
        with open("prompts/task1_sys_instruct_async.txt", 'r', encoding='utf-8') as f:
            return f.read().strip()

    async def locate_pages(self, pages):
        page:Page = None
        for page in pages:
            try:
                if await page.locator("div.box-wrapper").is_visible(timeout=100):
                    self.page_1 = page
                    self.log(f"已锁定题目页面: {await page.title()}")
                elif await page.locator("label:nth-child(34)").is_visible(timeout=100):
                    self.page_2 = page
                    self.log(f"已锁定搜索页面: {await page.title()}")
            except Exception as e:
                self.log(f"页面定位异常。")
                self.log({e})
        
        if not self.page_1:
            self.log("!!! 警告: 未找到题目页面。")
        if not self.page_2:
            self.log("!!! 警告: 未找到搜索页面。")

    async def _get_current_sn(self):
        try:
            sn_locator = self.page_1.locator("td > a:nth-child(2)")
            await sn_locator.wait_for(state="visible", timeout=10000)
            return await sn_locator.inner_text()
        except Exception:
            return ""

    # 单页数据获取
    async def collect_onepage_data(self):
        if self.page_1 == None or self.page_2 == None:
            self.log(f"页面未定位，非法操作。")
            return ("", "")

        if await self.page_1.locator("div.box-wrapper").is_visible(timeout=100) == 0 or await self.page_2.locator("label:nth-child(34)").is_visible(timeout=100) == 0:
            self.log(f"非目标页面，请重连。")
            return ("", "")

        if self.page_1.is_closed() or self.page_2.is_closed():
            self.log(f"***※目标页面已关闭※***")
            return ("", "")

        sn = await self._get_current_sn()
        if not sn:
            self.log(f"***※未能获取SN※***")
            return ("", "")

        self.log(f"当前题目SN: {sn}")
        self.log(".../正在获取题目信息")
        imgs = await self.problem_screenshot(self.page_1)
        if imgs == None :
            self.log(f"！！！截图失败！！！")
            return (sn, "")
        self.log(f"正在OCR/...")
        problem_alltext = await self.problem_ocr(self.pic2base64(imgs))
        self.log("OCR 已完成")
        answer = await self.jump_and_search_copy_and_return(self.page_1, self.page_2)
        self.log(f"本页题目信息获取完成")

        return (sn, {"problem": problem_alltext, "answer": answer})

    # 收纳所有数据
    async def gather_alldata(self):
        '''基于collect_onepage_data()，
        对从当前页面开始之后的所有页面进行信息存储，
        完成存储后，返回整数1。'''

        self.input_dataset = {}
        self.output_dataset = {}

        if self.page_1 == None or self.page_2 == None:
            self.log(f"页面未定位，非法操作。")
            return ""

        if await self.page_1.locator("div.box-wrapper").is_visible(timeout=100) == 0 or await self.page_2.locator("label:nth-child(34)").is_visible(timeout=100) == 0:
            self.log(f"非目标页面，请重连。")
            return ""

        if self.page_1.is_closed() or self.page_2.is_closed():
            self.log(f"***※目标页面已关闭※***")
            return ""

        try:
            if await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").is_visible():
                init_num_str = await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").input_value(timeout = 500)
                self.log(f"当前页页码为{init_num_str}")
                final_num_str = await self.page_1.locator(".tablebar:nth-child(2) span").inner_text()
                self.log(f"当前尾页页码为{final_num_str}")
                init_num = int(init_num_str)
                index = int(init_num_str)
                final_num = int(final_num_str)
                self.log(f"即将处理{final_num - init_num + 1}条数据")
            else:
                self.log(f"***※并发模式不支持仅一题※***")
                return ""
        except Exception as e:
            self.log(f"***确认页码范围错误***")
            self.log({e})

        for _ in range(init_num, final_num + 1):
            await asyncio.sleep(0.2)
            sn = await self.page_1.locator("td > a:nth-child(2)").inner_text()
            if index <= final_num:
                if sn in self.input_dataset:
                    await self.page_1.locator(".tablebar:nth-child(6) .tedit:nth-child(4)").click()
                else:
                    sn, data = await self.collect_onepage_data()
                    await self.page_1.locator(".tablebar:nth-child(6) .tedit:nth-child(4)").click()
                    index = index + 1
                    self.input_dataset[sn] = data
            else:
                self.log(f"当前序列采集完成。")
                break
            if data == "":
                self.log(f"***获取题目数据出现异常，任务终止***")
                return ""
        return 1

    # 对problem以及choices（若有）进行ocr前的编码
    def pic2base64(self, picpath: tuple) -> list:
        choices_path, problem_path = picpath
        content_payload = []
        
        try:
            with open(problem_path, "rb") as f:
                problem_base64 = base64.b64encode(f.read()).decode("utf-8")
            
            if choices_path:
                with open(choices_path, "rb") as f:
                    choices_base64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            self.log(f"文件读取错误: {e}")

        content_payload.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{problem_base64}"}})
        if choices_path:
            content_payload.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{choices_base64}"}})
        # 删除截图
        try:
            if os.path.exists(problem_path):
                os.remove(problem_path)
            if choices_path and os.path.exists(choices_path):
                os.remove(choices_path)
        except Exception as e:
            self.log(f"清理截图文件失败: {e}")

        return content_payload    

    # 强制基于qwenVL的ocr
    async def problem_ocr(self, base64pic_contentpayload) -> str:
        if os.getenv("QWEN_API_KEY") == '1':
            self.log(f"请引入QwenAPI以至少进行图像识别。")
            return "" 
        problem_alltext = await self.analyser.call_analyser(base64pic_contentpayload, '99')
        return problem_alltext 

    async def total_analyse(self):
        '''核心并发调用'''
        if not self.input_dataset:
            self.log(f"***采集数据过程异常，请联系调试***")
            return ""
        try:
            sns = list(self.input_dataset.keys())
            async_tasks = [self.analyser.call_analyser(json.dumps(self.input_dataset[sn], ensure_ascii=False), self._user_input, self.sys_instruct_AI()) for sn in sns]
            raw_results = await asyncio.gather(*async_tasks, return_exceptions=True)
            for sn, r in zip(sns, raw_results):
                self.output_dataset[sn] = r if not isinstance(r, Exception) else ""
            failed = sum(1 for r in raw_results if isinstance(r, Exception) or r == "")
            if failed:
                self.log(f"***※ {failed}/{len(raw_results)} 条并发调用失败 ※***")
            return 1
        except Exception as e:
            self.log(f"***并发调用API出现错误***")
            self.log(str({e}))

    
    async def execute(self):
        start_time = time.perf_counter()
        if await self.gather_alldata() == 1:
            self.log(f"当前批次信息采集已完成。")
            self.log(f".../正在并发调用API审核.../")
            if await self.total_analyse() == 1:
                self.log(f"当前批次信息已处理。")
                end_time = time.perf_counter()
                self.log(f"耗时{end_time-start_time:.2f}")
        else:
            return

        # 返回首页
        await self.page_1.locator(".tablebar:nth-child(2) .tedit:nth-child(1)").click()

        # SN 驱动的结果轮询
        previous_sn = ""
        while not self.stop.is_set():
            current_sn = await self._get_current_sn()
            if current_sn == previous_sn:
                await asyncio.sleep(0.1)
                continue

            if current_sn in self.output_dataset:
                self.result(self.output_dataset[current_sn])
            else:
                self.result("当前题目不在本批次中")
            previous_sn = current_sn
            await asyncio.sleep(0.1)

    async def problem_screenshot(self, operator_page: Page):
        '''依靠特定页面元素定位，对题目进行截图'''

        if not operator_page:
            self.log("目标页面未找到")
            return None

        problem_sn = ""
        save_path_choices = ""
        save_path_problem = ""
        script_path = os.path.dirname(os.path.abspath(__file__))

        try:
            asyncio.sleep(0.2)
            problem_sn_locator = operator_page.locator("td > a:nth-child(2)")
            await problem_sn_locator.wait_for(state="visible", timeout=10000)
            problem_sn = await problem_sn_locator.inner_text()
        except Exception as e:
            self.log(f"***※未能找到题目SN※***: {e}")

        if problem_sn:
            try:
                choices_locator = operator_page.locator("table.ques").first
                if await choices_locator.count() > 0:
                    save_path_choices = script_path + f"{problem_sn}_problem_choices.png"
                    clone_handle = await choices_locator.evaluate_handle("""original => {
                        const clone = original.cloneNode(true);
                        Object.assign(clone.style, {
                            position: 'absolute', top: '0', left: '0', width: 'auto',
                            height: 'auto', maxHeight: 'none', overflow: 'visible',
                            zIndex: '2147483647', backgroundColor: '#ffffff', padding: '20px'
                        });
                        document.body.appendChild(clone);
                        return clone;
                    }""")
                    await clone_handle.screenshot(path=save_path_choices)
                    await clone_handle.evaluate("el => el.remove()")
                else:
                    self.log("※非选择题※")
            except Exception as e:
                self.log(f"***※选项截图失败※***: {e}")
            
            try:
                problem_locator = operator_page.locator("div#Mark_Content_" + problem_sn)
                await problem_locator.wait_for(state="visible",timeout=10000)
                save_path_problem = script_path + f"{problem_sn}_problem.png"
                clone_handle = await problem_locator.evaluate_handle("""original => {
                    const clone = original.cloneNode(true);
                    Object.assign(clone.style, {
                        position: 'absolute', top: '0', left: '0', width: 'auto',
                        height: 'auto', maxHeight: 'none', overflow: 'visible',
                        zIndex: '2147483647', backgroundColor: '#ffffff', padding: '20px'
                    });
                    document.body.appendChild(clone);
                    return clone;
                }""")
                await clone_handle.screenshot(path=save_path_problem)
                await clone_handle.evaluate("el => el.remove()")
            except Exception as e:
                self.log(f"题目截图错误: {e}")
 
        return (save_path_choices, save_path_problem) if problem_sn else None

    async def jump_and_search_copy_and_return(self, page1: Page, page2: Page):
        '''依照特定页面逻辑与元素，获取题目答案'''

        if not page2: return "无法获取第二页面"
        problem_sn = await page1.locator("td > a:nth-child(2)").first.inner_text()
        
        try:
            await page2.bring_to_front()
            search_input = page2.locator("input#SName")
            search_button = page2.locator("input#SSearch")
            await search_input.fill(problem_sn)
            await page2.wait_for_timeout(300)
            await search_button.click()
            await page2.locator("div#Method_" + problem_sn).click()
            await page2.locator("input.code").click()
            
            iframe = page2.frame_locator("#htmlSourceFrame")
            textarea = iframe.locator("textarea#htmlSource")
            await textarea.click()
            await page2.wait_for_timeout(300)
            await page2.keyboard.press("Control+A")
            await page2.keyboard.press("Control+C")
            answer = pyperclip.paste()
            await page2.locator("input.hclose:nth-child(2)").click()
            await page1.bring_to_front()
            return answer
        except Exception as e:
            self.log(f"搜索复制失败: {e}")
            await page1.bring_to_front()
            return ""

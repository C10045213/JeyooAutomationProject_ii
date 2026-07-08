import re

# ---------- 工具函数 ----------
def is_chinese_char(ch):
    """判断是否为中文字符（基本汉字）"""
    return 0x4E00 <= ord(ch) <= 0x9FFF

def is_chinese_or_punct(ch):
    """判断是否为中文汉字或中文标点（用于分段）"""
    if is_chinese_char(ch):
        return True
    if ch in '，。！？；：“”‘’（）《》【】…—．':
        return True
    return False

# ---------- 配置：中文序列前后缀字符集 ----------
_CJK_PUNCT = '，。！？；：“”‘’（）《》【】…—．'
_PREFIX_CHARS = set(_CJK_PUNCT + ",.;:!?&=$\\")
_SUFFIX_CHARS = set(_CJK_PUNCT + ",.;:!?&=$\\")
# ---------- LaTeX 辅助函数 ----------
_DOLLAR_MATH_RE = re.compile(r'(?<!\\)\$((?:\\.|[^$])*?)(?<!\\)\$', re.DOTALL)

def _find_dollar_math_ranges(text):
    """返回 $...$ 数学区域的 (start, end) 列表"""
    ranges = []
    for m in _DOLLAR_MATH_RE.finditer(text):
        ranges.append((m.start(), m.end()))
    return ranges

def _consume_latex_block(text, i):
    """从 \\ 开始消费一个完整的 LaTeX 命令块，返回结束位置。
    对于 \\begin{env}，消费到匹配的 \\end{env}（处理嵌套）。"""
    j = i + 1
    if j >= len(text) or not text[j].isalpha():
        return j  # 转义字符（\{、\}、\\ 等），只跳过 \ 本身
    while j < len(text) and text[j].isalpha():
        j += 1
    cmd = text[i+1:j]
    if j < len(text) and text[j] == '*':
        j += 1
    while j < len(text) and text[j] == '{':
        depth = 1
        j += 1
        while j < len(text) and depth > 0:
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
            elif text[j] == '\\':
                j = _consume_latex_block(text, j)
                continue
            j += 1
    if cmd == 'begin':
        env_name_start = i + len('begin') + 1
        while env_name_start < len(text) and text[env_name_start] != '{':
            env_name_start += 1
        if env_name_start < len(text) and text[env_name_start] == '{':
            brace_depth = 1
            nb = env_name_start + 1
            ne = nb
            while ne < len(text) and brace_depth > 0:
                if text[ne] == '{':
                    brace_depth += 1
                elif text[ne] == '}':
                    brace_depth -= 1
                ne += 1
            env_name = text[nb:ne-1]
            begin_marker = '\\begin{' + env_name + '}'
            end_marker = '\\end{' + env_name + '}'
            depth = 1
            search_pos = j
            while depth > 0 and search_pos < len(text):
                nb_pos = text.find(begin_marker, search_pos)
                ne_pos = text.find(end_marker, search_pos)
                if ne_pos == -1:
                    break
                if nb_pos != -1 and nb_pos < ne_pos:
                    depth += 1
                    search_pos = nb_pos + len(begin_marker)
                else:
                    depth -= 1
                    search_pos = ne_pos + len(end_marker)
            j = search_pos
    return j

def _wrap_chinese_in_text(text):
    """在 $...$ 数学区域内，将符合前后缀特征的中文序列用 \\text{} 包裹"""
    ranges = _find_dollar_math_ranges(text)
    if not ranges:
        return text
    replacements = []
    for math_start, math_end in ranges:
        inner = text[math_start+1:math_end-1]
        base = math_start + 1
        i = 0
        n = len(inner)
        while i < n:
            if is_chinese_char(inner[i]):
                j = i
                while j < n and (is_chinese_char(inner[j]) or
                                 inner[j].isdigit() or
                                 ('a' <= inner[j].lower() <= 'z')):
                    j += 1
                prefix_ok = (i == 0) or (inner[i-1] in _PREFIX_CHARS)
                suffix_ok = (j >= n) or (inner[j] in _SUFFIX_CHARS)
                if prefix_ok and suffix_ok:
                    wrapped = '\\text{' + inner[i:j] + '}'
                    replacements.append((base + i, base + j, wrapped))
                i = j
            else:
                i += 1
    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    return text

# ---------- 清理函数 ----------
def clean_text(text):
    # 0. 捕获<图片>
    imgs = re.findall(r'<img[^>]*>', text)
    # 0.5 捕获<表格>
    tables = re.findall(f'<table[\s\S]*?<\/table>', text)
    # 1. 删除零宽字符
    text = text.replace('​', '')
    # 2. 处理 &nbsp; 并删除所有空格
    text = text.replace('&nbsp;', ' ')
    text = re.sub(r'\s+', '', text)
    # 3. 添加花括号转义
    text = processing_curlybrace(text)
    # 4. 转换上下标
    text = re.sub(r'<sup>([^<]*)</sup>', r'$^{\1}$', text)
    text = re.sub(r'<sub>([^<]*)</sub>', r'$_{\1}$', text)
    # 5. 删除html标记
    text = re.sub(r'<[^>]*>', '', text)
    # 5.5 将 $...$ 公式区域内的中文序列用 \text{} 包裹
    text = _wrap_chinese_in_text(text)
    # 6. 删除所有 $ 符号
    text = text.replace('$', '')
    # 7. 统一为英文括号
    text = text.replace('（', '(').replace('）', ')')
    return imgs, tables, text.strip()

# ---------- 添加 $ 符号（按中文/非中文分段） ----------
def add_dollar_to_math(text):
    if not text:
        return text
    segments = []
    i = 0
    n = len(text)
    while i < n:
        j = i
        typ = is_chinese_or_punct(text[i])
        while j < n:
            if not typ and text[j] == '\\':
                cmd_end = _consume_latex_block(text, j)
                if cmd_end > j:
                    j = cmd_end
                    continue
            if is_chinese_or_punct(text[j]) != typ:
                break
            j += 1
        segments.append((text[i:j], typ))
        i = j

    out_parts = []
    for seg, typ in segments:
        if typ:   # 中文/标点，原样
            out_parts.append(seg)
        else:     # 非中文，用 $ 包裹
            out_parts.append('$' + seg + '$')
    return ''.join(out_parts)

# ---------- 恢复含有中文内容的英文括号为中文括号 ----------
def restore_chinese_parentheses(text):
    """将内容包含中文字符的英文括号对转换为中文括号"""
    stack = []
    to_replace = []  # (左括号索引, 右括号索引)
    for i, ch in enumerate(text):
        if ch == '(':
            stack.append(i)
        elif ch == ')':
            if stack:
                left = stack.pop()
                content = text[left+1:i]
                # 检查内容是否包含中文字符
                if any(is_chinese_char(c) for c in content):
                    to_replace.append((left, i))
    # 从后往前替换，避免索引偏移
    for left, right in reversed(to_replace):
        text = text[:left] + '（' + text[left+1:right] + '）' + text[right+1:]
    return text

# ---------- 将字符串中未转义的花括号 { 和 } 转义为 \{ 和 \} ----------
def escape_braces(text):
    """将字符串中未转义的花括号 { 和 } 转义为 \{ 和 \}"""
    text = re.sub(r'(?<!\\)\{', r'\\{', text)  # 前面没有 \ 的 {
    text = re.sub(r'(?<!\\)\}', r'\\}', text)  # 前面没有 \ 的 }
    return text

def processing_curlybrace(text):
    """
    只跳过 $...$ 行内公式，其余所有内容的花括号都转义。
    公式内部原样保留（无论是否已转义）。
    """
    # 匹配行内公式 $...$（非贪婪，跳过转义的 \$）
    pattern = r'(?<!\\)\$(.*?)(?<!\\)\$'

    # 找到所有行内公式的起止位置
    ranges = []
    for match in re.finditer(pattern, text, re.DOTALL):
        ranges.append((match.start(), match.end()))

    # 如果没有公式，直接转义整个文本
    if not ranges:
        return escape_braces(text)

    # 分段处理：普通文本 -> 转义；公式 -> 原样保留
    result = []
    last_end = 0
    for start, end in ranges:
        # 公式前的普通文本
        if start > last_end:
            result.append(escape_braces(text[last_end:start]))
        # 公式本身（原封不动）
        result.append(text[start:end])
        last_end = end
    # 最后剩余的普通文本
    if last_end < len(text):
        result.append(escape_braces(text[last_end:]))
    return ''.join(result)

# 杂项
def fix_miscellaneous(text):
    text = text.replace("$，$", "，")
    text = text.replace("．", "。")
    return text

def remove_br_in_table(match):
    return match.group(0).replace("<br>", "")

# ---------- 主流程 ----------
def process_text(raw_text):
    # 预处理表格中的<br>
    raw_text = re.sub(r'<table[\s\S]*?<\/table>', remove_br_in_table, raw_text)
    # 再换行分块
    parts = raw_text.split('<br>')
    results = []
    for part in parts:
        imgs, tables ,cleaned = clean_text(part)
        if imgs:
            for img in imgs:
                results.append(img)
        if tables:
            for table in tables:
                results.append(table)
        if cleaned:
            next1 = restore_chinese_parentheses(cleaned)
            next2 = add_dollar_to_math(next1)
            final =fix_miscellaneous(next2)
            results.append(final + '\n')
    return ''.join(results)

# ========== 测试 ==========
if __name__ == '__main__':
    raw1 = """<img alt="菁优网" src="https://img.jyeoo.net/quiz/images/201405/17/bcf9b72a.png" style="vertical-align: middle; float: right; cursor: pointer;">解：令x=rcosθ，y=rsinθ．则r≤sinθ，且θ∈[0，π]，dσ=rdrdθ．<br>因此，\u200b$\\underset{D}{∬}$\u200b\u200b$\\sqrt{1-x^{2}-y^{2}}dσ$\u200b=\u200b$∫_0^π∫_0^{sinθ}$\u200b\u200b$\\sqrt{1-r^{2}}rdrdθ$\u200b．<br>令u=1-r<sup>2</sup>，则du=-2rdr，<br>积分限从r=0到r=sinθ对应u=1到u=cos<sup>2</sup>θ，<br>则\u200b${∫}_{0}^{sinθ}\\sqrt{1-r^{2}}rdr$\u200b=\u200b$\\frac{1}{2}$\u200b\u200b${∫}_{cos^{2}θ}^{1}\\sqrt{u}du$\u200b=\u200b$\\frac{1}{3}$\u200b（1-cos<sup>3</sup>θ），<br>故\u200b$∫_{0}^{π}$\u200b\u200b$\\frac{1}{3}（1-cos^{3}θ）dθ$\u200b=\u200b$\\frac{1}{3}$\u200b（\u200b$∫_{0}^{π}$\u200b1dθ-\u200b$∫_{0}^{π}$\u200bcos<sup>3</sup>θdθ）．<br> 又\u200b$∫_{0}^{π}$\u200b1dθ=π，而\u200b$∫_{0}^{π}$\u200bcos<sup>3</sup>θdθ=0（奇函数在对称区间积分）．<br>故原积分=\u200b$\\frac{1}{3}π$\u200b．"""
    raw2 = """解：在D上被积函数分块表示$max\\{{x^2}，{y^2}\\}=\\left\\{\\begin{array}{l}{x^2}，x≥y\\\\{y^2}，x≤y\\end{array}\\right.（x，y）∈D$，<br>于是要用分块积分法，用y=x将D分成两块：D=D<sub>1</sub>∪D<sub>2</sub>，D<sub>1</sub>=D∩{y≤x}，D<sub>2</sub>=D∩{y≥x}．<br>$I=\\underset{∫∫}{{D}_{1}}{e}^{max{{x}^{2}，{y}^{2}}}dxdy+\\underset{∫∫}{{D}_{2}}{e}^{max{{x}^{2}，{y}^{2}}}dxdy$= $\\underset{∫∫}{{D}_{1}}{e}^{{x}^{2}}dxdy+\\underset{∫∫}{{D}_{2}}{e}^{{y}^{2}}dxdy=2\\underset{∫∫}{{D}_{1}}{e}^{{x}^{2}}dxdy$<br>=$2∫_0^1{dx∫_0^x{e^{x^2}}}dy$=$2∫_0^1{x{e^{x^2}}}dx={e^{x^2}}|_{0^1}=e-1$．"""
    raw3 = """某地区有100名大学生参加环保知识竞赛，设获一、二、三等奖的人数分别为10，25及65，现从中随意挑选一名学生，若设$X_{i}=\\left\\{\\begin{array}{l}1，抽到获i等奖（i=1，2，3）的学生\\\\ 0，否则\\end{array}\\right.$．试求：<br>（1）随机变量X<sub>1</sub>与X<sub>3</sub>的联合分布律；<br>（2）方差D（X<sub>3</sub>-X<sub>1</sub>）；<br>（3）X<sub>1</sub>与X<sub>3</sub>的协方差Cov（X<sub>1</sub>，X<sub>3</sub>）．"""
    raw4 = """解：<br>（1）<br>∵随机变量Y服从参数λ=1的指数分布，<br>∴Y的分布函数为：F<sub>Y</sub>（y）=​$\\left\\{\\begin{array}{l}{1-{e}^{-y}}&{，y＞0}\\\\{0}&{，y≤0}\\end{array}$​，<br>由于随机变量X<sub>k</sub>=​$\\left\\{\\begin{array}{l}{0，若Y≤k}\\\\{1，若Y＞k}\\end{array}$​（k=1，2），<br>从而，（X<sub>1</sub>，X<sub>2</sub>）的可能取值为：（0，0）、（0，1）、（1，0）、（1，1），<br>有：<br>P{X<sub>1</sub>=0，X<sub>2</sub>=0}=P{Y≤1，Y≤2}=P{Y≤1}=F<sub>Y</sub>（1）=1-​$\\frac{1}{e}$​，<br>P{X<sub>1</sub>=0，X<sub>2</sub>=1}=P{Y≤1，Y＞2}=P{Y=∅}=0，<br>P{X<sub>1</sub>=1，X<sub>2</sub>=0}=P{Y＞1，Y≤2}=P{1＜Y≤2}=F<sub>Y</sub>（2）-F<sub>Y</sub>（1）=e<sup>-1</sup>-e<sup>-2</sup>，<br>P{X<sub>1</sub>=1，X<sub>2</sub>=1}=P{Y＞11，Y＞2}=P{Y＞2}=1-F<sub>Y</sub>（2）=e<sup>-2</sup>，<br>于是，得到X<sub>1</sub>和X<sub>2</sub>的联合概率分布列：<br><table class="edittable">\n  <tbody>\n    <tr>\n      <td width="189">&nbsp;&nbsp;X<sub>1</sub><br>&nbsp; X<sub>2</sub></td>\n      <td width="189">0</td>\n      <td width="189">1</td>\n    </tr>\n    <tr>\n      <td>0</td>\n      <td>1-e<sup>-1</sup>&nbsp;</td>\n      <td>e<sup>-1</sup>-e<sup>-2</sup>&nbsp;</td>\n    </tr>\n    <tr>\n      <td>1</td>\n      <td>0</td>\n      <td>e<sup>-2</sup>&nbsp;</td>\n    </tr>\n  </tbody>\n</table>（2）<br>由（1）求得的X<sub>1</sub>和X<sub>2</sub>的联合概率分布列，<br>可知：X<sub>1</sub>和X<sub>2</sub>服从0-1分布，<br>即：X<sub>k</sub>～​$（\\begin{array}{l}{0}&{1}\\\\{P（Y≤k）}&{P（Y＞k）}\\end{array}）=（\\begin{array}{l}{0}&{1}\\\\{1-{e}^{-k}}&{{e}^{-k}}\\end{array}）$​，k=1，2<br>∴E（X<sub>k</sub>）=P{X<sub>k</sub>=1}=e<sup>-k</sup>，k=1，2，<br>从而：E（X<sub>1</sub>+X<sub>2</sub>）=EX<sub>1</sub>+EX<sub>2</sub>=e<sup>-1</sup>+e<sup>-2</sup>．"""
    lines = process_text(raw1)
    print(lines)
    lines = process_text(raw2)
    print(lines)
    lines = process_text(raw3)
    print(lines)
    lines = process_text(raw4)
    print(lines)

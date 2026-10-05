# -*- coding: utf-8 -*-
"""Build the offline design gallery and deterministic, editable flowchart.

This script does not alter any generated image or application code.
"""
from pathlib import Path
from html import escape
import json

ROOT = Path(__file__).resolve().parent
boards = json.loads((ROOT / 'prompts.json').read_text(encoding='utf-8'))['boards']
pages = [
    [('A01', '正在启动'), ('A02', '首页'), ('A03', '选择训练人数'), ('A04', '确认玩家')],
    [('B01', '单人准备'), ('B02', '双人准备'), ('B03', '训练倒计时'), ('B04', '竞速倒计时')],
    [('C01', '单人训练'), ('C02', '双人训练'), ('C03', '双人竞速'), ('C04', '结束确认')],
    [('D01', '暂停'), ('D02', '单路信号中断'), ('D03', '页面连接中断'), ('D04', '急停锁定')],
    [('E01', '单人成果'), ('E02', '双人成果'), ('E03', '竞速结果'), ('E04', '报告状态')],
    [('F01', '我的记录'), ('F02', '详细报告'), ('F03', '教师设置'), ('F04', '系统维护')],
]

# SVG is authored from explicit nodes/edges, so labels and routes are editable.
svg = ['''<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1240" viewBox="0 0 1440 1240" role="img" aria-labelledby="title desc">
<title id="title">FOCUS 完整页面流程图</title><desc id="desc">学生从首页选择单人训练、双人训练或竞速，确认玩家、设备就绪并倒计时后进入游戏；完成后查看成果与历史。暂停、断连和急停分别处理。教师设置与系统维护使用独立入口。</desc>
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#7290ac"/></marker></defs>
<style>text{font-family:system-ui,'Microsoft YaHei',sans-serif;fill:#173350}.title{font-size:30px;font-weight:750}.sub{font-size:16px;fill:#56708a}.nodeTitle{font-size:20px;font-weight:700}.nodeSub{font-size:15px;fill:#56708a}.line{fill:none;stroke:#7290ac;stroke-width:2.5;marker-end:url(#arrow)}.label{font-size:14px;fill:#56708a}</style>
<rect width="1440" height="1240" fill="#f1f7fd"/>
<text x="42" y="50" class="title">FOCUS · 完整页面流程</text>
<text x="42" y="80" class="sub">页面编号对应 6 组样图 · 点击节点查看对应设计组 · 三种玩法沿用后台规则</text>''']

def text(x, y, value, css='sub'):
    svg.append(f'<text x="{x}" y="{y}" class="{css}">{escape(value)}</text>')

def node(x, y, w, title, sub, board, color='#258bff', height=86):
    svg.append(f'<a href="index.html#{board}" target="_top"><rect x="{x}" y="{y}" width="{w}" height="{height}" rx="15" fill="white" stroke="#cbddeb"/><rect x="{x}" y="{y+17}" width="5" height="{height-34}" rx="2" fill="{color}"/>')
    text(x+18, y+34, title, 'nodeTitle'); text(x+18, y+61, sub, 'nodeSub')
    svg.append('</a>')

def line(path, label=None, x=0, y=0):
    svg.append(f'<path d="{path}" class="line"/>')
    if label:
        text(x, y, label, 'label')

node(40, 112, 200, 'A01 等待启动', '后台就绪后进入', '01-entry')
node(292, 112, 210, 'A02 首页', '训练 / 竞速 / 记录', '01-entry')
node(568, 112, 320, 'A03–A04 选择与确认', '训练选人数；竞速固定双人', '01-entry')
node(970, 112, 420, 'B01–B02 设备准备', '检查连接、佩戴、校准和数据新鲜度', '02-ready')
line('M240 155 H292'); line('M502 155 H568'); line('M888 155 H970')
node(970, 235, 420, 'B03–B04 统一倒计时', '指定玩家全部就绪 + 后台允许', '02-ready')
line('M1180 198 V235')
text(48, 282, '未就绪：留在准备页说明原因；倒计时异常：停止倒计时，重新检查。')
svg.append('<path d="M1180 321 V350 H252 M700 350 H1180" fill="none" stroke="#7290ac" stroke-width="2.5"/>')
for x, name, sub, color in [(90,'C01 单人训练','1 个仪表盘 + 个人趋势','#258bff'), (538,'C02 双人训练','2 个仪表盘 + 各自目标','#258bff'), (986,'C03 双人竞速','2 辆小车 + 双车道','#f69a35')]:
    line(f'M{x+163} 350 V384')
    node(x, 384, 326, name, sub, '03-play', color)
for x, name, sub, color in [(90,'E01 单人成果','个人指标，不生成能力评价','#258bff'), (538,'E02 双人成果','分别回顾，不默认排名','#258bff'), (986,'E03 竞速结果','胜负 / 平局；注明虚拟成绩','#f69a35')]:
    line(f'M{x+163} 470 V529', '自然完成或 C04 确认结束', x+14, 505)
    node(x, 529, 326, name, sub, '05-results', color)
svg.append('<path d="M253 615 V647 H1149 V615 M701 615 V647" fill="none" stroke="#7290ac" stroke-width="2.5"/>')
line('M701 647 V678')
node(486, 678, 430, 'F01 历史 → F02 详细报告', '按玩家与条件查询；完整保存后导出', '06-teacher')
node(970, 678, 420, 'E04 报告异常状态', '样本不足与保存失败分别表达', '05-results', '#dc992d')
line('M1149 647 H1180 V678')
text(48, 719, '再来一次 → 玩家确认与设备准备')
text(48, 749, '回到首页 → A02；不自动开始新一场')

svg.append('<rect x="30" y="794" width="1380" height="225" rx="20" fill="#e7f0fa"/>')
text(49, 829, '游戏过程中：按异常类型处理，不自动跳过安全检查', 'nodeTitle')
for x, title, sub, color in [(49,'D01 手动暂停','动力归零；暂停不计有效时长','#258bff'), (392,'D02 单路无信号','该路停止，另一玩家继续','#e39b27'), (735,'D03 页面失联','禁用操作；后台按超时停输出','#e39b27'), (1078,'D04 急停锁定','全部停输出；老师排查并复位','#d85865')]:
    node(x, 849, 310, title, sub, '04-states', color)
text(49, 970, '暂停恢复：手动继续 → 就绪检查 → 倒计时；重连不自动恢复动力。')
text(49, 997, '急停复位：返回准备再开始；双路无信号按本轮固定规则处理（体验继续计时 / 正式中断）。')

node(49, 1054, 340, '教师入口', '从 A02 首页进入', '01-entry')
node(485, 1054, 420, 'F03 教师设置', '时长 / 个人目标 / 规则；开场固定', '06-teacher')
node(975, 1054, 415, 'F04 系统维护', '设备 / 模式 / 日志 / 配置与版本', '06-teacher')
line('M389 1097 H485')
line('M219 1140 V1160 H1182 V1140')
text(49, 1190, '模式、个人目标、保护状态与结果均来自后台；画面动画只负责展示。')
text(49, 1219, '设计概念稿 · 样图数值为示例 · 并非现有运行页面截图')
svg.append('</svg>')
(ROOT / 'flow.svg').write_text('\n'.join(svg), encoding='utf-8')

cards = []
for board, group in zip(boards, pages):
    name = escape(board['file']); title = escape(board['title'])
    labels = ''.join(f'<li><b>{pid}</b> {escape(label)}</li>' for pid, label in group)
    cards.append(f'''<section id="{name}" class="board"><div class="section-head"><div><p class="eyebrow">{name[:2]} / DESIGN BOARD</p><h2>{title}</h2></div><a class="button" href="{name}.png" target="_blank">打开原图 ↗</a></div><button class="image-button" data-image="{name}.png" data-title="{title}" aria-label="放大{title}"><img src="{name}.png" alt="{title}：{'、'.join(label for _, label in group)}" loading="lazy"></button><ul class="page-list">{labels}</ul></section>''')
nav = ''.join(f'<a href="#{b["file"]}">{i+1:02} {escape(b["title"])}</a>' for i, b in enumerate(boards))
html = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>FOCUS · 完整流程与页面设计</title><style>
:root{font-family:system-ui,'Microsoft YaHei',sans-serif;color:#173350;background:#eff6fd}
*{box-sizing:border-box}
body{margin:0}
a{color:#126acf;text-decoration:none}
button{font:inherit}
header{background:#ffffffee;border-bottom:1px solid #d4e3f1;padding:18px 5%;display:flex;align-items:center;justify-content:space-between;gap:20px}
header strong{font-size:24px;color:#103e74}
.pill{background:#fff0c8;color:#805c12;padding:8px 13px;border-radius:25px;font-size:14px}
main{max-width:1240px;margin:0 auto;padding:42px 24px}
h1{font-size:clamp(28px,4vw,46px);margin:12px 0}
h2{font-size:26px;margin:0}
p{line-height:1.75;color:#58718a}
.eyebrow{font-size:12px;letter-spacing:2px;color:#367bc8;margin:0 0 7px}
.intro{max-width:800px}
.nav{display:flex;flex-wrap:wrap;gap:10px;margin:24px 0 34px}
.nav a,.button{background:#fff;border:1px solid #c7dced;border-radius:10px;min-height:44px;padding:11px 16px;display:inline-flex;align-items:center}
.nav a:hover,.button:hover{border-color:#2189ff;background:#eaf5ff}
.board{background:white;border:1px solid #d9e5ef;border-radius:20px;padding:22px;margin:25px 0 42px;scroll-margin-top:18px;box-shadow:0 10px 35px #16395d07}
.section-head{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:18px}
.image-button{display:block;width:100%;border:0;padding:0;background:#eaf3fc;border-radius:14px;overflow:hidden;cursor:zoom-in}
img{display:block;width:100%;height:auto}
.page-list{padding:0;list-style:none;display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:0}
.page-list li{font-size:14px;line-height:1.7;color:#58718a}
.page-list b{color:#173350;margin-right:5px}
.flow{width:100%;height:auto;border:0;border-radius:14px;aspect-ratio:1440/1240}
.notes{padding:24px;border-left:4px solid #258bff;background:#e5f1fd;border-radius:0 16px 16px 0;line-height:1.9;color:#45627e}
.notes ul{padding-left:22px;margin:8px 0}
footer{font-size:14px;color:#58718a;padding:28px 0}
dialog{width:96vw;max-width:1800px;max-height:95vh;border:0;border-radius:16px;padding:15px;overflow:auto;background:#f3f8fd}
dialog::backdrop{background:#0b254be0}
dialog .section-head{position:sticky;top:-15px;background:#f3f8fdf0;padding:10px 0;z-index:1}
dialog h2{font-size:20px}
dialog button{cursor:pointer}
dialog img{width:100%}
body:has(dialog[open]){overflow:hidden}
@media(max-width:700px){main{padding:25px 12px}
.board{padding:12px;border-radius:14px}
.page-list{grid-template-columns:1fr 1fr}
.section-head{align-items:start}
h2{font-size:21px}
header{padding:14px 16px}
.pill{font-size:12px}
.button{padding:9px 11px;font-size:14px}
}
@media print{header,.nav,dialog{display:none}
.board{break-inside:avoid;box-shadow:none}
main{padding:0}
.image-button{border:0}
.flow{height:850px}
.button{display:none}
}

</style></head><body><header><strong>◉ FOCUS / DESIGN</strong><span class="pill">视觉概念稿 · 非运行界面</span></header><main><p class="eyebrow">YOUTH EXPERIENCE / V2</p><h1>从开始到成果，每一步都看得懂。</h1><p class="intro">完整流程总图 + 24 个页面与状态样图。延续蓝橙配色、明亮卡片和大触摸按钮，覆盖单人训练、双人训练、双人竞速，以及准备、异常、成果和教师管理。点击任意样图放大；所有资源可离线浏览。</p><nav class="nav"><a href="#flow">完整流程图</a>''' + nav + '''</nav><section id="flow" class="board"><div class="section-head"><div><p class="eyebrow">00 / USER FLOW</p><h2>完整页面流程图</h2></div><a class="button" href="flow.svg" target="_blank">放大流程图 ↗</a></div><object class="flow" data="flow.svg" type="image/svg+xml" aria-label="完整页面流程图"><a href="flow.svg">打开流程图</a></object><p>箭头表达主要导航路径；暂停、断连、急停适用于游戏过程。样图上的编号可在下方逐项对照。</p></section>''' + ''.join(cards) + '''<aside class="notes"><b>从设计稿到程序实现时，需要保持的规则</b><ul><li>单人和双人训练均保留；双人训练不默认判胜负，竞速才展示比赛结果。</li><li>模拟体验始终有标识；虚拟车辆位置不代表实体小车的传感器实测位置。</li><li>仪表盘、目标区和车辆位置按后台数值精确绘制，生成图中的刻度只作视觉参考。</li><li>断连是无效数据，不显示为零分；页面失联不能宣称已确认硬件停止，重连不自动恢复动力。</li><li>普通结束需要确认；急停立即提交，不增加确认弹窗。复位后仍需准备和重新开始。</li><li>样本不足和保存失败是两种独立状态；成果页不得将不完整记录标为保存成功。</li><li>所有示例数值、昵称和记录均为设计演示；教师设置、维护入口及细节以最终接口实现为准。</li></ul></aside><footer>使用内置 image_gen 生成 6 组视觉稿；流程图以可编辑 SVG 编写。<a href="prompts.json">完整生成提示词</a> · <a href="README.md">页面清单与设计说明</a></footer></main><dialog id="viewer"><div class="section-head"><h2 id="viewer-title"></h2><button class="button" id="close">关闭 ✕</button></div><img id="viewer-image" alt=""></dialog><script>
const viewer=document.getElementById('viewer');document.querySelectorAll('[data-image]').forEach(button=>button.addEventListener('click',()=>{document.getElementById('viewer-title').textContent=button.dataset.title;const image=document.getElementById('viewer-image');image.src=button.dataset.image;image.alt=button.dataset.title;viewer.showModal()}));document.getElementById('close').addEventListener('click',()=>viewer.close());viewer.addEventListener('click',event=>{if(event.target===viewer)viewer.close()});
</script></body></html>'''
(ROOT / 'index.html').write_text(html, encoding='utf-8')

readme = ['# FOCUS 青少年界面完整设计稿 v2', '', '本目录是设计评审材料，不替换应用代码，也不是已实现功能的运行截图。', '', '打开 `index.html` 可离线浏览全部样图并点击放大。`flow.svg` 为可编辑、可放大的完整流程总图。', '', '## 页面清单', '', '| 组别 | 页面／状态 | 图片 |', '| --- | --- | --- |']
for board, group in zip(boards, pages):
    readme.append(f'| {board["title"]} | '+ '、'.join(f'{pid} {name}' for pid, name in group) + f' | [{board["file"]}.png]({board["file"]}.png) |')
readme += ['', '## 交互约定', '', '- 开场确认本轮模式、人数、目标和规则；双人训练与竞速均需两路就绪。', '- 暂停归零且暂停时长不计入有效时长；继续需状态检查和倒计时。', '- 单路无信号只停止该路；全部无信号按固定会话规则执行。', '- 页面失联禁用依赖旧状态的操作，后台按心跳超时停止输出；恢复连接不自动恢复动力。', '- 急停无需确认；明确排查和复位后返回准备，不直接继续旧输出。', '- 报告读取与导出不参与控制循环；记录不完整时不能显示保存成功。', '- 学生成果先看个人过程；教师详情保留原始／平滑数据和事件。', '', '## 生成与编辑', '', '6 张视觉稿使用内置 image_gen 生成。参考前一版三屏样图，完整最终提示词保存在 `prompts.json`。若存在修订，另存 edit-prompts.json。原图直接复制保存，没有用程序修改生成图像。', '', '`build_gallery.py` 只构建 HTML 和手工定义的 SVG 流程图，不生成或修改 PNG。图片上的示例读数与刻度不构成算法规范，实现时以后台数据与产品规则为准。', '', '## 后续实现', '', '先评审三种核心玩法与准备流程，再迁移组件；真实头环佩戴示意需按实际设备修订。样图里的教师入口、复位与权限文字代表拟定交互，最终必须由后台校验。']
(ROOT / 'README.md').write_text('\n'.join(readme)+'\n', encoding='utf-8')
print('Built index.html, flow.svg, README.md')

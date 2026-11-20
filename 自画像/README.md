# 自画像 · 本地个人资料库

这里收录从公开资料采集到依都读取的完整流程。脚本只用 Python 3.10+ 标准库，在 `自画像` 目录运行。以下命令用 PowerShell，先把账号和联系方式替换成自己的。

```powershell
New-Item -ItemType Directory -Force 本机数据
python collect_bangumi.py your_username 本机数据/bangumi.json --user-agent 'Windowletters/1.0 (your-contact@example.com)'
python collect_bilibili.py 123456 本机数据/bilibili-dynamics.jsonl --detail
python collect_bilibili.py 123456 本机数据/bilibili-articles.jsonl --articles
```

- Bangumi 通过公开收藏接口按页读取，保留有评分或短评的记录和作品链接。用户名可从个人主页地址中取得。[Bangumi API v0](https://github.com/bangumi/api/blob/master/open-api/v0.yaml)
- B 站使用账号空间的公开动态和专栏索引。动态默认保存预览，`--detail` 尝试补正文。专栏索引提供标题和摘要。本文本流程保存帖子链接，遇到平台限流或正文不可用时可导入已有缓存。网页接口由站点维护，访问情况会变化。[哔哩哔哩开放平台](https://open.bilibili.com/doc)
- 两个采集脚本都支持 `--max-pages`。B 站两种采集模式分别写文件，中途遇到错误时，之前写入的 JSONL 记录还可入库。

用一个或多个输入构建 SQLite。只填实际拿到的输入即可。重建时用新文件名。

```powershell
python build_library.py 本机数据/个人信息.sqlite3 --bangumi 本机数据/bangumi.json --bilibili 本机数据/bilibili-dynamics.jsonl --bilibili 本机数据/bilibili-articles.jsonl
python 生成查看页.py 本机数据/个人信息.sqlite3 本机数据/查看个人信息库.html
python export_context.py 本机数据/个人信息.sqlite3 本机数据/Gemini_人格卡素材.txt --post-limit -1
```

### 导入旧缓存和人工整理的资料

- `--bilibili-cache <目录>` 兼容之前多轮采集留下的 `index.json` 和 `details*.jsonl`。也可通过 `--bilibili-db <文件>` 导入早期带 `posts` 表的本地归档。对同一个帖子 ID，保留已有的全文。
- `--notes <文件>` 导入人工核对过的档案条目。支持「本人自述」「本人观点」「跨帖归纳」「表达样本」四种依据。引文逐字核对原帖和 ID 后入库，避免把模型归纳误写为本人自述。模板如下，`evidence` 可留空。

```json
{
  "profile": {"title": "我的资料库"},
  "items": [
    {
      "category": "偏好",
      "label": "纸质书",
      "statement": "通勤时常看短篇小说。",
      "basis": "本人自述",
      "context": "自填",
      "evidence": []
    }
  ]
}
```

引用 B 站来源时，在 `evidence` 内添加 `{"post_id": "本库中的帖子 ID", "quote": "正文中的原句"}`。索引里的专栏 ID 形如 `cv123456`。导出的 TXT 可用于人工撰写人格卡，编辑后把选定内容放进依都的人格卡。

在启动[依都夜谈](../依都夜谈/)前，把 `ITO_PERSONAL_KB_PATH` 设为库文件绝对路径。数据库旁可放 `个人信息补充汇总.md`，用二级标题和列表补充要点。机器人按当前话题检索相关条目和作品短评。

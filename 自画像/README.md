# 自画像 · 本地个人资料库

从 `schema.sql` 建空 SQLite 库，再填入自己的作品短评、帖子摘记和资料条目。用下面的命令生成离线查看页。

```powershell
python 生成查看页.py 个人信息.sqlite3 查看个人信息库.html
```

要让[依都夜谈](../依都夜谈/)读取，设置 `ITO_PERSONAL_KB_PATH` 为库文件绝对路径。数据库旁也可放一份 `个人信息补充汇总.md`。

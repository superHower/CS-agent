# tests/fixtures/

测试数据目录，按店铺拆分子目录，模拟多店铺场景。

## 目录结构

```
fixtures/
├── messages/           # 模拟平台推送消息（各平台原始格式 JSON）
│   ├── taobao/
│   ├── pinduoduo/
│   ├── jd/
│   └── douyin/
├── obsidian/           # 迷你 Obsidian 测试知识库
│   ├── tb_demo_001/    # 淘宝示例店铺知识库
│   └── pdd_demo_001/   # 拼多多示例店铺知识库
└── configs/            # 测试用配置文件片段
```

## 使用方式

测试中通过相对路径引用 fixture：

```python
FIXTURES_DIR = Path(__file__).parent
MSG_DIR = FIXTURES_DIR / "messages"
OBSIDIAN_DIR = FIXTURES_DIR / "obsidian"
```

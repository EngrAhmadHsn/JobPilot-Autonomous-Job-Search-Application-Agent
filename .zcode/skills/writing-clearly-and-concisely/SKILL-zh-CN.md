---
name: writing-clearly-and-concisely
description: "当你在写人类要读的 prose 时使用，例如文档、提交说明、错误消息、解释、报告或 UI 文案。本技能应用 Strunk 的经典写作规则，使文本更清楚、更有力、更专业。"
---

# 写得清楚且简洁 (Writing Clearly and Concisely)

## 概览 (Overview)

写作要清楚，也要有力量。这个技能既讲“应该做什么”（Strunk），也讲“不该做什么”（常见 AI 写作模式）。

## 何时使用本技能 (When to Use This Skill)

只要你在写给人类看的 prose，就该用这个技能：

- 文档、README、技术解释
- 提交信息（commit message）、PR 描述
- 错误消息、UI 文案、帮助文本、注释
- 报告、摘要，或任何解释型文本
- 为了提升清晰度而做编辑

**只要你在写要给人读的句子，就用这个技能。**

## 上下文受限时的策略 (Limited Context Strategy)

当上下文紧张时：

1. 先凭判断写出草稿
2. 把草稿和相关章节文件一起分发给 subagent
3. 让 subagent 做 copyedit，并返回修订稿

只加载一个章节（约 1,000 到 4,500 tokens），而不是把全部内容都塞进上下文，能明显节省空间。

## 风格要素 (Elements of Style)

William Strunk Jr. 的 *The Elements of Style*（1918）教你如何写得清楚，并且毫不留情地删掉废话。

### 规则 (Rules)

**用法基础规则（Elementary Rules of Usage，语法/标点）：**

1. 单数名词的所有格加 `'s`
2. 并列系列中，除最后一项外，每项后都加逗号
3. 插入语两侧都要用逗号
4. 在引出并列分句的连词前加逗号
5. 不要用逗号连接独立分句
6. 不要把一句话硬拆成两句
7. 句首分词短语应对应语法主语

**写作基本原则（Elementary Principles of Composition）：**

8. 一段只讲一个主题
9. 段首先给主题句
10. **使用主动语态（active voice）**
11. **用肯定表达（positive form）**
12. **使用明确、具体、具象的语言**
13. **删去不必要的词**
14. 避免一连串松散句子
15. 并列思想用相似形式表达
16. **相关词放在一起**
17. 摘要中保持时态一致
18. **把强调词放在句末**

### 参考文件 (Reference Files)

上面的规则是对 Strunk 原文的摘要。完整解释和示例请看：

| 章节（Section） | 文件（File） | ~Tokens |
|---------|------|---------|
| 语法、标点、逗号规则 | `02-elementary-rules-of-usage.md` | 2,500 |
| 段落结构、主动语态、简洁表达 | `03-elementary-principles-of-composition.md` | 4,500 |
| 标题、引语、格式 | `04-a-few-matters-of-form.md` | 1,000 |
| 选词、常见错误 | `05-words-and-expressions-commonly-misused.md` | 4,000 |

**大多数任务只需要 `03-elementary-principles-of-composition.md`**，因为它覆盖主动语态、肯定表达、具体语言和删掉废词。

## 需要避免的 AI 写作模式 (AI Writing Patterns to Avoid)

LLM 很容易回归统计均值，产出泛泛、膨胀的 prose。要避免：

- **空泛夸饰（Puffery）：** pivotal、crucial、vital、testament、enduring legacy
- **空洞的 `-ing` 短语：** ensuring reliability、showcasing features、highlighting capabilities
- **宣传式形容词：** groundbreaking、seamless、robust、cutting-edge
- **高频 AI 词汇：** delve、leverage、multifaceted、foster、realm、tapestry
- **过度格式化：** 过多 bullets、emoji 装饰、隔几个词就加粗

要具体，不要浮夸。直接说它实际做了什么。

如果想看这些模式为何会出现的完整研究，请看 `signs-of-ai-writing.md`。Wikipedia 编辑基于真实审核经验总结了这套识别 AI 投稿的指南，模式成熟且经过实战验证。

## 底线 (Bottom Line)

只要是在给人写东西：加载 `elements-of-style/` 下相关章节并应用这些规则。对大多数任务而言，`03-elementary-principles-of-composition.md` 已经覆盖了最关键的部分。

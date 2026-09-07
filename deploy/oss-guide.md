# 阿里云对象存储（OSS）备份指南（初学者版）

这份文档解释 OSS 是什么、怎么开通、怎么给每日备份当异地副本、怎么控制
费用、怎么在服务器丢失时从 OSS 恢复。全程不需要写代码。

每一步都标明了在哪里执行：**（浏览器）**= 阿里云控制台网页，**（Mac）**=
你的电脑终端，**（服务器）**= SSH 登录服务器后的终端。

## OSS 是什么（三句话分清三个存放处）

- **ACR** 存软件镜像：你发布的程序本身（`skill-eval-web`/`skill-eval-api` 镜像）。
- **服务器**运行程序并保存当前数据：题目、文件、数据库都在服务器的盘上。
- **OSS** 存导出的备份文件：`backup.py` 每天把数据库和文件导出成一个归档
  （`latest.tar.gz`），上传一份到 OSS，作为服务器盘损坏/误删时的异地副本。

两个常见误解：

- 备份**不是**在原数据库里加历史表，数据库里始终只有当前数据；
- 备份**不是**数据库容器镜像——`postgres:16-alpine` 镜像只是软件，
  你的业务数据在 pgdata 卷里，必须导出才算备份。

留存策略：**服务器、OSS、Mac 三处都只保留最新成功的一套**，新一轮成功
后自动替换上一轮。没有 7 天/30 天历史；三处全部替换之后，不存在更早的
逻辑恢复点。这是明确选择的代价：误删数据若在当日备份后被三处替换，
无法回到误删前。

## 第一步：核对免费试用资格（浏览器）

1. 登录阿里云控制台，搜索"对象存储 OSS"进入产品页；
2. 新用户免费试用规则（以页面实时展示为准）：**实名认证**且**从未开通
   过 OSS** 的用户可领取试用包，当前规则大致为：标准本地冗余存储 20 GB
   / 3 个月、外网流出流量 2 GB / 3 个月、请求 20 万次 / 3 个月；
3. 资格是否可领、具体额度以控制台"免费试用"页面为准。**试用不等于永久
   免费**，到期后按量计费继续；本文档不承诺你的账号一定能领到。

开通 OSS 服务本身免费；花钱的是存储量、请求次数和公网流出流量（按小时
结算）。官方示例单价（以实际定价页为准）：标准本地冗余存储约 0.12 元
/GB/月。按"只留一套"的策略，若完整归档 1 GB，稳态存储费每月约 0.12 元，
另有少量请求费；替换期间新旧两套短暂共存属正常。

## 第二步：开通并创建私有 Bucket（浏览器）

1. 首次进入按提示**开通 OSS**（如已领取试用包会自动关联）；
2. 控制台 → OSS → Bucket 列表 → 创建 Bucket：
   - 地域：与服务器**同地域**（服务器在北京就选华北2-北京）——这是内网
     免流量费的前提；
   - 存储类型：标准存储；
   - 读写权限：**私有**（绝不选公共读）；
   - **版本控制：不开启**；**保留策略（WORM）：不设置**——`backup.py`
     检测到这两项会拒绝上传并要求人工处理，因为只留一套的策略与它们冲突；
3. 记下 Bucket 名称（全局唯一，例如 `skill-eval-backup-你的名字`）。

这个 Bucket 专用于备份，不要放网站静态资源或其他业务内容；工具只管理
专用前缀内的对象，不会也不应与其他内容混用。

## 第三步：创建最小权限 RAM 用户（浏览器）

不要用主账号 AccessKey。

1. 控制台搜索"RAM 访问控制" → 用户 → 创建用户：
   - 访问方式勾选"使用永久 AccessKey 访问"；
   - 创建完成后**立刻保存** AccessKey ID 和 Secret（只显示一次）；
2. 给该用户授权：权限策略 → 创建权限策略 → 脚本编辑，粘贴（把
   `你的Bucket名` 和 `你的前缀` 换成实际值，前缀与 `.env` 的 `OSS_PREFIX`
   一致，例如 `skill-eval-backups`）：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["oss:GetObject", "oss:PutObject", "oss:DeleteObject", "oss:AbortMultipartUpload"],
      "Resource": ["acs:oss:*:*:你的Bucket名/你的前缀/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["oss:ListObjects", "oss:ListParts"],
      "Resource": ["acs:oss:*:*:你的Bucket名"],
      "Condition": {"StringLike": {"oss:Prefix": ["你的前缀/*"]}}
    },
    {
      "Effect": "Allow",
      "Action": ["oss:GetBucketVersioning", "oss:GetBucketWorm"],
      "Resource": ["acs:oss:*:*:你的Bucket名"]
    }
  ]
}
```

3. 把该策略授权给刚创建的 RAM 用户。

这个权限只能读写专用前缀内的对象、列出该前缀、终止该前缀的分片上传，
以及读取 Bucket 的版本控制/保留锁状态（`backup.py` 预检需要）。它不能
删除 Bucket、不能改保护策略、不能碰前缀之外的对象。

## 第四步：服务器上安装并配置 ossutil（服务器）

```bash
# 安装（版本以官方下载页为准，2.x 即可；工具同时兼容 ossutil64 命令名）
curl -o /usr/local/bin/ossutil https://gosspublic.alicdn.com/ossutil/v2/2.1.1/ossutil-2.1.1-linux-amd64
chmod +x /usr/local/bin/ossutil
ossutil --version

# 配置凭证：按提示输入第三步的 AccessKey ID/Secret
# endpoint 一栏填同地域内网地址（见第五步说明），也可留到 .env 统一配置
ossutil config
```

ossutil 的凭证保存在服务器 `~/.ossutilconfig`（root 可读）。**AccessKey
绝不写进 `.env`、绝不提交 Git**；`.env` 里只有 Bucket 名、前缀和内网
Endpoint 三个非机密配置。

## 第五步：填写 .env 的 OSS 配置（服务器）

```bash
cd /opt/skill-eval
vi .env
```

三项都不含密钥（模板注释见 `deploy/.env.production.example`）：

```
OSS_BUCKET=你的Bucket名
OSS_PREFIX=skill-eval-backups
OSS_ENDPOINT=oss-cn-beijing-internal.aliyuncs.com
```

**同地域内网 Endpoint**（带 `-internal`）：服务器与 Bucket 同地域时走
内网，**不收流量费**（存储和请求仍计费）；`backup.py` 的上传与发布前
回读校验都走这个地址。Mac 公网恢复下载不使用此配置。

改完重启不必需——`backup.py` 每次运行都通过 `docker compose config`
读取最新值。

## 第六步：验证首次上传（服务器）

```bash
bash /opt/skill-eval/backup.sh
```

成功输出会分别给出两处结果：

- `服务器副本已更新：备份 ID ...，生成时间 ...`
- `OSS 副本：已发布 <备份ID> ...`

以及最后一行 `完整备份成功`。OSS 失败不会回滚服务器副本，但最后一行会
改为"服务器完整备份成功；OSS 本次更新失败，云端仍指向上一次成功备份"，
且前面明确说"OSS 副本：本次更新失败"——按提示排查（常见：AccessKey
权限不足、Endpoint 写错、Bucket 开了版本控制），次日备份会自动重试。

（浏览器）到控制台 → Bucket → 文件管理，应看到 `skill-eval-backups/`
前缀下恰好一个 `latest.json` 和 `bundles/` 里一个 `.tar.gz`。

## 第七步：费用检查与提醒（浏览器）

1. 控制台搜索"费用与成本" → 账单详情 → 按产品筛选"对象存储 OSS"，
   每月看一次实际扣费（存储/请求/流量分项）；
2. 费用 → 预算管理：创建一个小额预算（例如 10 元/月）并绑定手机/邮件
   提醒，超出即收到通知；
3. 免费试用到期前会收到通知；到期后如不再需要，按下一步清理并停用。

工具端不会替你监控账单；"只看到一个对象"也不等于没有隐藏计费——按
第八步定期检查分片残留。

## 第八步：保留与清理（只留最新一套）

正常情况**不需要手动清理**：`backup.py run` 每轮先处理专用前缀内本工具
拥有的未发布候选与旧对象，发布新指针后才删除精确的上一对象；不删除指针
指向的对象，不递归清空 Bucket，不改 Bucket 保护策略。

每 1-3 个月做一次残留检查（服务器）：

```bash
# 专用前缀内的对象清单：稳态应只有 latest.json + bundles/ 下一个 .tar.gz
ossutil ls oss://你的Bucket名/skill-eval-backups/

# 未完成分片上传清单：稳态应为空；工具每轮也会显式终止自己的分片
ossutil ls oss://你的Bucket名/skill-eval-backups/bundles/ --multipart
```

发现前缀外的意外对象、或 Bucket 被开启了版本控制/保留锁：不要自行用
脚本清空，人工在控制台核实来源后处理（版本控制会让"删除"只产生删除
标记，历史版本继续计费——这正是工具拒绝在这种 Bucket 上运行的原因）。

## 第九步：恢复下载（服务器没了的时候）

日常 Mac 下载**不从 OSS 走**（见 `README.md` 的 Mac 每日下载章节）；
OSS 只在服务器不可用时作为恢复来源。

在任意装好 Python 3.10+ 和 ossutil 的机器上（Mac 或替代服务器）：

```bash
# 1) 先读指针，拿到当前恢复点的对象名、备份 ID、大小和整包 SHA-256
ossutil cat oss://你的Bucket名/skill-eval-backups/latest.json

# 2) 下载指针对象名对应的完整归档（把 <object> 换成上一步 object 字段的值）
mkdir -p /tmp/restore
ossutil cp oss://你的Bucket名/skill-eval-backups/<object> /tmp/restore/latest.tar.gz

# 3) 核对整包摘要与指针一致（输出应为 latest.json 里的 sha256 值）
shasum -a 256 /tmp/restore/latest.tar.gz    # Mac
# 或 sha256sum /tmp/restore/latest.tar.gz   # Linux 服务器

# 4) 结构与密钥校验
python3 backup.py restore-check /tmp/restore/latest.tar.gz --aes-key-file <密钥文件>
```

- Mac 走公网下载会产生 OSS **外网流出流量费**（约 0.5 元/GB 量级，以
  定价页为准），下载前确认归档大小与账单影响；
- 如果第 2 步报对象不存在（恰好撞上服务器端并发更新删除了旧对象），
  重新执行第 1 步获取最新指针再下载一次；仍失败则保留目标端旧归档并
  排查，不要无限重试；
- 恢复导入按 `restore.md` 执行；校验失败不开放写入。

## 常见问题

**backup.py 报"Bucket 已启用版本控制"**
创建时开了版本控制或后来被人打开。只留一套的策略要求关闭它（控制台 →
Bucket → 版本控制），或换一个专用 Bucket；工具不会替你静默关闭保护。

**backup.py 报"存在保留锁（WORM）策略"**
Bucket 上有合规保留策略，锁定期间对象不可删除。人工在控制台处理，
工具不会绕过。

**上传报 denied / AccessDenied**
RAM 策略的 Resource 前缀与实际 `OSS_PREFIX` 不一致，或用了没有授权的
AccessKey。对照第三步逐项核对。

**想确认到底花了多少钱**
费用与成本 → 账单详情 → 按 Bucket/计费项查看；免费试用额度消耗也在
同一页面。本文档给的所有价格都是示例，以控制台实时账单为准。

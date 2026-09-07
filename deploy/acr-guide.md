# 阿里云容器镜像服务（ACR）使用指南（初学者版）

这份文档解释 ACR 是什么、怎么开通、怎么把镜像推上去、服务器怎么拉下来。
全程在浏览器和终端完成，不需要写代码。

## ACR 是什么

镜像仓库 = 存放 Docker 镜像的网盘。

- 你的 Mac 把构建好的镜像**推送（push）**上去
- 服务器从里面**拉取（pull）**下来运行
- 服务器因此完全不需要接触你的源代码，也不用访问 GitHub

选阿里云自家的 ACR 是因为：它和你的北京服务器在同一个云区域内，拉取走内网，速度快、不花公网流量费，个人版免费。

## 第一步：开通个人版

1. 登录阿里云控制台，顶部搜索"容器镜像服务"
2. 首次进入会让你选择版本：选**个人版**（免费；企业版是给大团队用的，你不需要）
3. 按提示完成开通（可能需要设置一个初始密码，记下来）

## 第二步：创建命名空间和镜像仓库

ACR 里镜像的完整地址长这样：

```
registry.cn-beijing.aliyuncs.com/<命名空间>/<仓库名>:<标签>
```

1. 左侧菜单"命名空间"→ 创建，名字用 `blue-benchmark`（小写，之后不可改）
2. 左侧菜单"镜像仓库"→ 创建，逐个创建 4 个仓库（都选**私有**、**本地仓库**）：
   - `blue-benchmark-web`（前端）
   - `blue-benchmark-api`（后端 + Worker 共用）
   - `nginx`（反向代理基础镜像，只推一次）
   - `postgres`（数据库基础镜像，只推一次）

创建完成后，你的镜像仓库地址前缀（后面叫 `REGISTRY`）就是：

```
registry.cn-beijing.aliyuncs.com/blue-benchmark
```

## 第三步：设置访问凭证

1. 左侧菜单"访问凭证"→ 设置**固定密码**（这是专门用于 docker login 的密码，不是阿里云账号密码，自己设一个好记但不同于其他网站的）
2. 记住你的阿里云账号全名（登录名），docker login 时用它做用户名

## 第四步：在你的 Mac 上登录并推送

```bash
# 登录（用户名=阿里云账号名，密码=上一步的固定密码）
docker login --username=你的阿里云账号名 registry.cn-beijing.aliyuncs.com

# 验证：推送一个测试标签
docker tag hello-world registry.cn-beijing.aliyuncs.com/blue-benchmark/hello:test 2>/dev/null || true
```

日常推送不需要手工执行：仓库里的 `deploy/push-images.sh` 会自动构建并推送
`blue-benchmark-web` 和 `blue-benchmark-api`（详见 `deploy/README.md` 的发版流程）。

### 一次性操作：把基础镜像转存到 ACR

服务器从 Docker Hub 直接拉镜像在国内不稳定，所以把 nginx 和 postgres 先转到
ACR，之后服务器只依赖 ACR：

```bash
docker pull --platform linux/amd64 nginx:1.27-alpine
docker pull --platform linux/amd64 postgres:16-alpine

docker tag nginx:1.27-alpine registry.cn-beijing.aliyuncs.com/blue-benchmark/nginx:1.27-alpine
docker tag postgres:16-alpine registry.cn-beijing.aliyuncs.com/blue-benchmark/postgres:16-alpine

docker push registry.cn-beijing.aliyuncs.com/blue-benchmark/nginx:1.27-alpine
docker push registry.cn-beijing.aliyuncs.com/blue-benchmark/postgres:16-alpine
```

> 仓库名和标签必须与 compose.yaml 中的镜像地址完全一致
> （`${REGISTRY}/nginx:1.27-alpine` 和 `${REGISTRY}/postgres:16-alpine`）。
> 如果你在服务器上把 `REGISTRY` 留空，compose 会退回 Docker Hub 默认源
> （国内拉取可能不稳定，建议始终配置 REGISTRY）。

## 第五步：在服务器上登录

SSH 登录服务器后执行一次：

```bash
docker login --username=你的阿里云账号名 registry.cn-beijing.aliyuncs.com
```

登录凭据会保存在服务器的 `~/.docker/config.json`。因为服务器用 root 运行
Docker，这个文件等于存放了 ACR 密码——不要把这个文件发给别人。

### 更快的内网地址（可选优化）

你的服务器是阿里云北京 ECS，可以用 VPC 内网域名拉取，更快且不占公网带宽：

```bash
docker login --username=你的阿里云账号名 registry-vpc.cn-beijing.aliyuncs.com
```

然后把服务器 `.env` 里的 `REGISTRY` 写成
`registry-vpc.cn-beijing.aliyuncs.com/blue-benchmark`。
（你的 Mac 推送仍然用公网域名 `registry.cn-beijing.aliyuncs.com`，两边不冲突。）

## 常见问题

**push 报 `denied: requested access to the resource is denied`**
没登录或命名空间/仓库名拼错。先 `docker login`，再核对地址里的命名空间和仓库名是否与第二步创建的完全一致。

**push 很慢**
镜像首次推送需要上传所有层，前端镜像约 150 MB、后端约 300 MB，家庭宽带上行需要几分钟是正常的。之后每次只推变化的层，会快很多。

**服务器 pull 报 `unauthorized`**
在服务器上重新执行一次 `docker login`。

**想看都推过哪些版本**
控制台 → 镜像仓库 → 选中仓库 → 镜像版本，能看到所有标签和推送时间。标签就是版本号（格式 `YYYYMMDD-<git短哈希>`）。

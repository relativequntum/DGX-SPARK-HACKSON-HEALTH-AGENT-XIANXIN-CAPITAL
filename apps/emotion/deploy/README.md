# 阶段三部署到 DGX Spark（judge + face_body）

两个模块都跑在 Spark 本机，不出网：

- **judge**（对话重点判断）调阶段二已部署的 llama-server（Qwen3.6-35B-A3B，`127.0.0.1:8080/v1`），
  能直接读数字人 consult_recorder 落盘的问诊记录；
- **face_body**（面部与身体观察）用 MediaPipe 在 CPU 上跑，不占 GPU；
- 结果放在 `~/spark-Hackson/outputs/`，由一个只监听 `127.0.0.1:8020` 的静态浏览服务提供，经 SSH 隧道看；
- 问诊结束后由自动判断服务跑 judge，结果出现在阶段二医生控制台的「重点」页签（控制台那边的改动走阶段二的分支）。

部署脚本不改阶段二的任何服务和文件，只读 llama-server 的 key 文件路径、问诊记录目录和数字人的在线会话接口。

## 一、从开发机部署（或更新）

前提：开发机能免密 `ssh` 到 Spark（把公钥加进 Spark 的 `~/.ssh/authorized_keys`）。

```bash
# 仓库根目录，Git Bash / Linux / macOS
SPARK_SSH="<用户>@<主机> -p <端口>" bash apps/emotion/deploy/deploy_spark.sh

# 某个模块要部署别的分支（例如测一个 PR 分支），单独指定它的 ref
JUDGE_REF=<分支、标签或提交> SPARK_SSH="<用户>@<主机> -p <端口>" bash apps/emotion/deploy/deploy_spark.sh
```

它用 `git archive` 取**已提交**的 `apps/emotion/{judge,face_body,deploy}`（Spark 访问不了 GitHub，所以不在上面 clone），
经 **1 条** SSH 连接传过去（Spark 的 SSH 通道上限 64 条）。三个模块各取 `JUDGE_REF` / `FACE_REF` / `DEPLOY_REF`（默认都是 `HEAD`）：

- ref 先在本地解析成提交；本地没有这个名字时改用 `origin/<ref>`（只认本地已 fetch 到的，所以先 `git fetch`）；
  本地分支和 `origin/` 同名分支不一致时照用本地的，并打印提醒；
- **ref 无效直接报错退出**，什么都不部署，不会静默沿用 Spark 上的旧版；
- ref 有效但里面没有这个模块的目录时跳过该模块，并打印「Spark 上的 <模块> 不更新，仍是上次部署的版本」；
  `DEPLOY_REF` 里没有 `apps/emotion/deploy` 时报错退出。

传过去以后在 Spark 上执行 `setup_spark.sh`：先把收到的模块换进 `~/spark-Hackson/apps/emotion/`、
在 `DEPLOYED_REFS` 里记下部署的提交，再依次做六步：

| 步 | 做什么 |
|---|---|
| 1 | 建 `~/emotion-venv`（Python 3.12），按 `requirements-spark.txt` 从阿里云镜像装依赖；清掉与 mediapipe 冲突的 `opencv-python-headless` |
| 2 | 下载 MediaPipe 模型到 `~/emotion-models/mediapipe` 并校验 sha256（已有且校验通过就跳过） |
| 3 | 分别跑 judge、face_body 的单元测试 |
| 4 | 检查 llama-server 在线、key 文件可读 |
| 5 | 装并重启 systemd 用户服务 `emotion-viewer`（`127.0.0.1:8020` → `outputs/`） |
| 6 | 装并重启常驻的 systemd 用户服务 `emotion-judge-watch`：问诊结束后自动跑 judge，结果写到 `outputs/judge/consult/` |

全部幂等，可以重复跑；在 Spark 上直接 `bash ~/spark-Hackson/apps/emotion/deploy/setup_spark.sh` 也能重跑这六步（不换代码）。

### 部署记录：`~/spark-Hackson/DEPLOYED_REFS`

每次部署给每个更新了的模块**追加**一行，不覆盖已有内容：

```text
<模块> <完整提交号> <Spark 上的 ISO 时间> <部署时写的 ref>
```

前三列与手工部署时记的「模块 提交号 时间」一致，两种来源的行可以放在同一个文件里。
看某个模块现在是哪个版本：`grep '^judge ' ~/spark-Hackson/DEPLOYED_REFS | tail -1`。
跳过的模块不记新行，它的最后一行就是 Spark 上现在的版本。

### 第 6 步与部署后核对

第 6 步只在部署的 judge 里有 `watch.py` 时执行（否则打印「跳过」）：把 `emotion-judge-watch.service` 装进
`~/.config/systemd/user/`、enable 并重启，等 3 秒后查 `is-active`。在线打印日志命令；没起来打印排查命令并以非 0 退出，
整次部署算失败。部署完可以这样核对：

```bash
tail -n 3 ~/spark-Hackson/DEPLOYED_REFS                     # 这次部署的模块和提交
systemctl --user is-active emotion-viewer emotion-judge-watch  # 两个都应是 active
journalctl --user -u emotion-judge-watch -n 20               # 只有会话编号前 8 位和命中数，没有对话内容
```

## 二、参数：在 Spark 上改用本机覆盖文件

`spark.env`（端口、目录、镜像、代理、llama-server 地址）随每次部署**整体替换**，在 Spark 上直接改它，下次部署就没了。
要在 Spark 上改的参数写进 `~/.config/emotion/spark.local.env`，它不在部署目录里，重新部署不会动它：

```bash
mkdir -p ~/.config/emotion
echo 'PROXY=http://<局域网代理>' >> ~/.config/emotion/spark.local.env   # 下载慢时：pip 和模型下载都会走它
bash ~/spark-Hackson/apps/emotion/deploy/setup_spark.sh               # 重跑一遍，服务才用上新参数（浏览服务的端口和目录是安装时写进服务文件的）
```

- 一行一个普通赋值（`变量=值`），变量名就是 `spark.env` 里那些；`spark.env` 最先读它，它写了的以它为准
  （也优先于命令行临时给的同名环境变量），没写的用 `spark.env` 的默认值；
- 由别的变量推出的默认值会跟着变：例如只写 `EMOTION_HOME=...`，`EMOTION_OUT` 也跟着到新目录下
  （改 `EMOTION_HOME` 时，开发机上 `deploy_spark.sh` 的 `REMOTE_HOME` 要一致）；
- 用了覆盖文件时，`setup_spark.sh` 开头会打印「用了本机覆盖参数」；想让所有人都用的默认值，改仓库里的 `spark.env` 再部署。

## 三、在 Spark 上跑

```bash
# 登录时多开一个隧道端口 8020 看结果（8010 / 3478 是数字人用的）
ssh -p <端口> -L 8010:127.0.0.1:8010 -L 3478:127.0.0.1:3478 -L 8020:127.0.0.1:8020 <用户>@<主机>

source ~/spark-Hackson/apps/emotion/deploy/spark.env && cd "$EMOTION_HOME" && PY="$EMOTION_VENV/bin/python"

# judge：一段虚构样本 / 5 段样本评测 / 数字人的全部问诊记录
$PY -m apps.emotion.judge run "apps/emotion/judge/samples/s01_胃胀失眠.json" --backend openai --out-dir "$EMOTION_OUT/judge"
$PY -m apps.emotion.judge.eval.run_eval --backend openai --out-dir "$EMOTION_OUT/judge/eval"
for f in "$CONSULT_DIR"/*.jsonl; do $PY -m apps.emotion.judge run "$f" --backend openai --out-dir "$EMOTION_OUT/judge/consult"; done

# face_body：数值报告 / 叠加打点的演示视频（H.264，浏览器能播）
$PY -m apps.emotion.face_body analyze <视频.mp4> --out-dir "$EMOTION_OUT/face_body"
$PY -m apps.emotion.face_body annotate <视频.mp4> --out-dir "$EMOTION_OUT/face_body"
```

然后本机浏览器打开 <http://127.0.0.1:8020/>：`judge/` 下是医生视图（`*.judge.html`），`face_body/` 下是报告 JSON、演示视频和关键帧。

## 问诊结束后自动出「重点」

`emotion-judge-watch` 常驻盯着 `~/livetalking-logs/consultations/`：

- 记录里出现总结（患者点了结束问诊），或 3 分钟没有新内容，就判断这次问诊；
- 每发一次请求前，先等 llama-server 空闲、数字人没有在线会话，最多等 10 分钟，不和实时问诊抢唯一的并发槽；
- 结果写到 `outputs/judge/consult/<会话>.judge.json`，医生控制台（8110）的「重点」页签读它，点一条跳回对话原句；
- 只用本地模型；日志只有会话编号前 8 位和命中数：`journalctl --user -u emotion-judge-watch -f`。

## 注意

- **llama-server 只有 1 个并发槽**（`--parallel 1`），和数字人的实时对话共用。有人在演示数字人时别跑批量评测，
  judge 每条回答两次请求，5 段样本评测约 3 分钟。
- 问诊记录与它的 judge 结果可能含真人说的话：只留在 Spark 上，不拷出来、不入库、不开 `--cloud`。
- face_body 的演示视频含人脸：只用于演示，演示完删；不要用真实患者视频。
- `outputs/` 不按人隔离，能登录这个账号的人都看得到。

## 卸载

```bash
systemctl --user disable --now emotion-viewer emotion-judge-watch
rm ~/.config/systemd/user/emotion-viewer.service ~/.config/systemd/user/emotion-judge-watch.service
rm -rf ~/spark-Hackson ~/emotion-venv ~/emotion-models ~/.config/emotion
```

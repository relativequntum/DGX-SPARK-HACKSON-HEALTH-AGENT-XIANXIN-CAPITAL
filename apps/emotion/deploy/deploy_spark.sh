#!/usr/bin/env bash
# 把阶段三模块（judge / face_body / deploy）从 git 传到 DGX Spark，再在 Spark 上执行 setup_spark.sh。
# 在开发机的仓库里跑（Git Bash / Linux / macOS），需要能免密 ssh 到 Spark。
#
#   SPARK_SSH="<用户>@<主机> -p <端口>" bash apps/emotion/deploy/deploy_spark.sh
#   JUDGE_REF=<分支/标签/提交> SPARK_SSH="..." bash apps/emotion/deploy/deploy_spark.sh   # 某个模块取别的 ref，例如测 PR 分支
#
# - Spark 访问不了 GitHub，所以不在 Spark 上 git clone：这里用 git archive 取**已提交**的内容，工作区改动不会上去；
# - 每个模块取自各自的 ref（JUDGE_REF / FACE_REF / DEPLOY_REF，默认都是 HEAD），先在本地解析成提交：
#   本地解析不了时试 origin/<ref>（只认本地已 fetch 到的远端分支，所以先 git fetch）；都解析不了就报错退出，
#   不会静默沿用 Spark 上的旧版；ref 有效但里面没有该模块目录时跳过该模块，Spark 上的这个模块保持原样；
# - 部署了什么记在 Spark 的 ~/$REMOTE_HOME/DEPLOYED_REFS：每个模块追加一行「模块 提交号 时间 ref」，不覆盖已有的行；
# - Spark 的 SSH 通道有上限（64 条）：全程只开 1 条连接；
# - 只替换 $REMOTE_HOME/apps/emotion/<模块>，不动 outputs/、模型目录和阶段二的任何东西。
set -euo pipefail
: "${SPARK_SSH:?请设置 SPARK_SSH，例如 SPARK_SSH=\"<用户>@<主机> -p <端口>\"}"
: "${JUDGE_REF:=HEAD}" "${FACE_REF:=HEAD}" "${DEPLOY_REF:=HEAD}"
: "${REMOTE_HOME:=spark-Hackson}"   # 相对 Spark 家目录，要与 spark.env 的 EMOTION_HOME 一致

cd "$(git rev-parse --show-toplevel)"

# 把 ref 解析成完整提交号，结果放进 sha 和 used（实际用的名字，可能补了 origin/）；解析不了返回 1
resolve_ref() {
  local ref="$1" remote
  used="$ref"
  if sha="$(git rev-parse --verify --quiet "$ref^{commit}")"; then
    # 本地分支与已 fetch 的 origin 同名分支不一致：照用本地的，但提醒一句
    if git show-ref --verify --quiet "refs/heads/$ref" &&
       remote="$(git rev-parse --verify --quiet "refs/remotes/origin/$ref^{commit}")" &&
       [ "$remote" != "$sha" ]; then
      echo "--  注意：本地 $ref（${sha:0:7}）与 origin/$ref（${remote:0:7}）不一致，用本地的；要部署远端版本请写 origin/$ref"
    fi
    return 0
  fi
  used="origin/$ref"
  sha="$(git rev-parse --verify --quiet "$used^{commit}")" || return 1
  echo "--  本地没有 $ref，改用 $used"
}

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
: > "$stage/DEPLOYED_REFS.pending"
for spec in judge:JUDGE_REF face_body:FACE_REF deploy:DEPLOY_REF; do
  mod="${spec%%:*}"
  var="${spec#*:}"
  ref="${!var}"
  if ! resolve_ref "$ref"; then
    echo "!! $var=$ref 不是有效的提交：本地和 origin/ 下都找不到（先 git fetch，或检查拼写）。没有部署任何东西" >&2
    exit 1
  fi
  if git cat-file -e "$sha:apps/emotion/$mod" 2>/dev/null; then
    # 关掉 autocrlf：Windows 开发机默认会把打包内容转成 CRLF，Spark 上的 bash 跑不了
    git -c core.autocrlf=false archive "$sha" "apps/emotion/$mod" | tar -x -C "$stage"
    printf '%s %s %s\n' "$mod" "$sha" "$used" >> "$stage/DEPLOYED_REFS.pending"
    echo "==> 打包 apps/emotion/$mod @ $used (${sha:0:7})"
  else
    echo "--  跳过 apps/emotion/$mod：$used（${sha:0:7}）里没有这个目录。Spark 上的 $mod 不更新，仍是上次部署的版本"
  fi
done
[ -f "$stage/apps/emotion/deploy/setup_spark.sh" ] ||
  { echo "!! 选中的 ref 里没有 apps/emotion/deploy，无法在 Spark 上安装" >&2; exit 1; }
grep -q 'DEPLOYED_REFS.pending' "$stage/apps/emotion/deploy/setup_spark.sh" ||
  echo "--  注意：DEPLOY_REF 里的 setup_spark.sh 是旧版，这次不会在 Spark 上写 DEPLOYED_REFS"

incoming="~/$REMOTE_HOME/.incoming"
# shellcheck disable=SC2086  # SPARK_SSH 需要按空格拆成 ssh 参数
tar -c -C "$stage" apps DEPLOYED_REFS.pending | ssh -o BatchMode=yes -o ServerAliveInterval=30 $SPARK_SSH \
  "rm -rf $incoming && mkdir -p $incoming && tar -x -C $incoming && bash $incoming/apps/emotion/deploy/setup_spark.sh --install-from $incoming"

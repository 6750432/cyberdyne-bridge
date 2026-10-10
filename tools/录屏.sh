#!/bin/bash
# 录屏 —— 用 ffmpeg 的 x11grab 抓桌面。主人自己测试时用。
#   开始：  bash ~/cyberdyne-bridge/tools/录屏.sh 开始 [文件名.mp4]
#   停  ：  bash ~/cyberdyne-bridge/tools/录屏.sh 停
#   状态：  bash ~/cyberdyne-bridge/tools/录屏.sh 状态
# ⚠ 变量名一律 ASCII（本机 locale 是 C，中文变量名会炸）
set -u
OUT_DIR="$HOME/Desktop/78/录像"
PIDFILE="/tmp/dafeiyu-record.pid"
# 画面尺寸：从 xdpyinfo 读，读不到就退回 1920x1080
SIZE=$(DISPLAY=:0 xdpyinfo 2>/dev/null | awk '/dimensions:/{print $2; exit}')
[ -z "${SIZE:-}" ] && SIZE="1920x1080"
# 帧率/画质：默认 30fps、CRF 23（够清楚又不太大）
FPS="${REC_FPS:-30}"
CRF="${REC_CRF:-23}"

case "${1:-}" in
  开始)
    mkdir -p "$OUT_DIR" || exit 1
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "已经在录了（pid $(cat "$PIDFILE")）—— 先「停」再开"; exit 1
    fi
    NAME="${2:-}"
    [ -z "$NAME" ] && NAME="石镐实测-$(date +%Y%m%d-%H%M%S).mp4"
    case "$NAME" in *.mp4) ;; *) NAME="$NAME.mp4" ;; esac
    OUT="$OUT_DIR/$NAME"
    setsid nohup env DISPLAY=:0 ffmpeg -hide_banner -loglevel warning \
      -f x11grab -framerate "$FPS" -video_size "$SIZE" -i :0.0+0,0 \
      -c:v libx264 -preset veryfast -crf "$CRF" -pix_fmt yuv420p \
      -movflags +faststart "$OUT" >/tmp/dafeiyu-record.log 2>&1 < /dev/null &
    echo $! > "$PIDFILE"
    sleep 2
    if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "🔴 开录了：$OUT"
      echo "   画面 $SIZE @ ${FPS}fps ｜ 停：bash ~/cyberdyne-bridge/tools/录屏.sh 停"
    else
      echo "❌ 没起来 —— 看 /tmp/dafeiyu-record.log"; tail -3 /tmp/dafeiyu-record.log
    fi
    ;;
  停)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      PID=$(cat "$PIDFILE")
      kill -INT "$PID" 2>/dev/null      # ffmpeg 收 SIGINT 才会把尾巴写完整
      for i in 1 2 3 4 5 6 7 8 9 10; do sleep 1; kill -0 "$PID" 2>/dev/null || break; done
      kill -0 "$PID" 2>/dev/null && kill -TERM "$PID" 2>/dev/null
      rm -f "$PIDFILE"
      sleep 1
      NEW=$(ls -t "$OUT_DIR"/*.mp4 2>/dev/null | head -1)
      echo "⏹ 停了。最新一条：$NEW"
      [ -n "$NEW" ] && ls -lh "$NEW"
    else
      echo "没在录"; rm -f "$PIDFILE"
    fi
    ;;
  状态)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "🔴 正在录（pid $(cat "$PIDFILE")）"
      ls -lh "$OUT_DIR"/*.mp4 2>/dev/null | tail -3
    else
      echo "⚪ 没在录"; ls -lh "$OUT_DIR"/*.mp4 2>/dev/null | tail -3
    fi
    ;;
  *)
    sed -n '2,8p' "$0"; exit 1;;
esac

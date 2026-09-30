#!/bin/bash
# 起 MC 服务端。跟着这个脚本走，免得每次都忘了 java 不在 PATH 里、忘了限优先级。
#   nice 10        —— 别跟主人的前台程序抢 CPU
#   ionice 2/6     —— 系统盘是机械硬盘，磁盘优先级压到最低档
cd "$(dirname "$0")/../runtime" || exit 1
J=/home/<用户>/cyberdyne-bridge/runtime/jre/usr/lib/jvm/java-21-openjdk-amd64/bin/java
exec nice -n 10 ionice -c2 -n6 "$J" -Xmx2G -jar server.jar nogui

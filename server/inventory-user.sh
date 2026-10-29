#!/bin/bash
# inventory-user.sh: what this server contains and who is using its GPUs, using only commands any user can run.
# It only reads. It needs no sudo, installs nothing, changes no settings and writes no files.
#
#   bash server/inventory-user.sh | less
#
# Each section prints a "== " header followed by the plain output of the commands under it.
# Everything is inside one { } block that reads from /dev/null, so no command can wait for keyboard input.
{
export LC_ALL=C
section() { printf '\n== %s\n' "$1"; }

section "host"
hostname -f
date '+%F %H:%M %Z'
uptime
grep PRETTY_NAME /etc/os-release
uname -r

section "system model and firmware date"
grep . /sys/class/dmi/id/{sys_vendor,product_name,board_vendor,board_name,bios_version,bios_date,chassis_type}

section "cpu"
lscpu

section "memory"
free -g

section "gpus"
lspci -nn | grep -Ei 'vga|3d controller|display controller'
timeout 60 nvidia-smi
timeout 60 nvidia-smi --format=csv --query-gpu=index,pci.bus_id,name,vbios_version,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw,power.limit,power.max_limit,pcie.link.gen.max,pcie.link.width.max,clocks_throttle_reasons.active
grep . /sys/class/drm/card*/device/{gpu_busy_percent,mem_info_vram_used,mem_info_vram_total} 2>/dev/null
grep . /sys/class/drm/card*/device/hwmon/hwmon*/{power1_average,power1_cap} 2>/dev/null

section "gpu holders (gpu, user, pid, memory)"
timeout 60 nvidia-smi --query-compute-apps=gpu_bus_id,pid,used_memory --format=csv,noheader |
    while IFS=', ' read -r bus pid mem unit; do echo "$bus $(ps -o user= -p "$pid") $pid $mem $unit"; done
for p in /sys/class/kfd/kfd/proc/*; do
    [ -e "$p" ] && echo "amd $(ps -o user= -p "${p##*/}") ${p##*/}"
done

section "network, storage and other controllers"
lspci | grep -Ei 'ethernet|network|infiniband|non-volatile|raid|sas|sata|scsi'

section "disks"
lsblk -e7 -o NAME,SIZE,TYPE,ROTA,TRAN,MODEL,MOUNTPOINT
timeout 30 df -hl -x tmpfs -x devtmpfs -x squashfs -x overlay -x efivarfs

section "network"
ip -br addr
grep . /sys/class/net/*/speed 2>/dev/null

section "restarts and shutdowns, newest first (a reboot with no shutdown below it = unclean restart)"
last -x -F reboot shutdown

section "failed services"
systemctl --failed --no-pager

printf '\n== END\n'
} </dev/null 2>&1

#!/bin/bash
# inventory-root.sh: the parts of the inventory only root can read: serial numbers, memory slots, power supplies,
# whole-server power, disk health, and the boot and error logs.
# It only reads. It installs nothing, changes no settings and writes no files.
#
#   sudo bash server/inventory-root.sh | less
#
# Each section prints a "== " header followed by the plain output of the commands under it.
# Everything is inside one { } block that reads from /dev/null, so no command can wait for keyboard input.
{
export LC_ALL=C
section() { printf '\n== %s\n' "$1"; }

if [ "$(id -u)" != 0 ]; then echo "inventory-root.sh must run as root"; exit 1; fi

section "identity"
hostname -f
date '+%F %H:%M %Z'
dmidecode -s system-manufacturer
dmidecode -s system-product-name
dmidecode -s system-serial-number
dmidecode -t chassis | grep -E 'Type:|Height:|Number Of Power Cords:'

section "memory slots"
dmidecode -t 16 | grep -E 'Maximum Capacity:|Number Of Devices:|Error Correction Type:'
dmidecode -t 17 | grep -E '^\s(Locator|Size|Type|Speed|Configured Memory Speed|Manufacturer|Part Number):'

section "power supplies (firmware table)"
dmidecode -t 39 | grep -E 'Location:|Name:|Manufacturer:|Max Power Capacity:|Status:'

section "bmc: whole-server power now"
timeout 60 ipmitool dcmi power reading

section "bmc: power supplies, fans, temperatures and event log (last 30)"
# ipmitool rebuilds an empty sensor list when it reads sensors (or names events), so these run only if the list has records.
if timeout 60 ipmitool sdr info | grep -Eq 'Record Count *: *[1-9]'; then
    timeout 60 ipmitool sdr type "Power Supply"
    timeout 60 ipmitool sdr type Fan
    timeout 60 ipmitool sdr type Temperature
    timeout 60 ipmitool sel elist last 30
else
    echo "no BMC, or its sensor list is empty: sensors not read"
fi

section "bmc: power restore policy"
timeout 60 ipmitool chassis status

section "disk health"
for d in $(lsblk -dno NAME -e7,11); do
    echo "-- /dev/$d"
    timeout 60 smartctl -n standby -H -i -A "/dev/$d"
done

section "root filesystem created (ext4 only; usually the OS install date)"
tune2fs -l "$(findmnt -no SOURCE /)" | grep 'Filesystem created'

section "restarts and shutdowns, older months, newest first (a reboot with no shutdown below it = unclean restart)"
last -x -F -f /var/log/wtmp.1 reboot shutdown

section "boots recorded in the journal"
timeout 120 journalctl --list-boots --no-pager

section "kernel errors, last 180 days (latest 100)"
timeout 300 journalctl _TRANSPORT=kernel -p err --since "-180 days" -n 100 --no-pager -q

printf '\n== END\n'
} </dev/null 2>&1

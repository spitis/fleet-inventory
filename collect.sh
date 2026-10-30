#!/bin/bash
# collect.sh: run one of the three scripts in server/ on every server in a list, over ssh, and save what it prints.
#
#   ./collect.sh hosts.txt user     # inventory-user.sh with your own account  -> reports/HOST-user.txt
#   ./collect.sh hosts.txt root     # inventory-root.sh through sudo -n         -> reports/HOST-root.txt
#   ./collect.sh hosts.txt usage    # usage.sh, one snapshot appended to reports/usage-YYYY-MM.log (run from cron)
#
# hosts.txt has one server per line; text after # is ignored (see hosts.txt.example).
# "root" needs your account to have sudo without a password on each server. Nothing ever asks for a password:
# ssh runs in batch mode and sudo -n fails instead of prompting, so a server without access fails with the reason.
# A server that fails keeps its earlier report. Afterwards reports/index.html is rebuilt.
# Extra ssh options, such as a key, can go in SSH_OPTS, e.g. SSH_OPTS="-i $HOME/.ssh/fleet_key".

hosts=$1
kind=$2
here=$(dirname "$0")
case $kind in
    user)  script=$here/server/inventory-user.sh; remote='bash -s' ;;
    root)  script=$here/server/inventory-root.sh; remote='sudo -n bash -s' ;;
    usage) script=$here/server/usage.sh;          remote='bash -s' ;;
    *)     echo "usage: $0 HOSTS_FILE user|root|usage"; exit 1 ;;
esac
[ -r "$hosts" ] || { echo "cannot read $hosts"; exit 1; }
limit=900                                   # seconds allowed per server
[ "$kind" = usage ] && limit=120            # so a usage run from cron ends before the next one starts

umask 077                                   # reports hold usernames, addresses and serial numbers
mkdir -p reports
exec 9> "reports/.lock-$kind"                # one run of each kind at a time
flock -n 9 || { echo "a $kind run is still going; skipped"; exit 1; }
failed=reports/not-collected-$kind.log      # listed at the top of index.html
: > "$failed"

run_one() {
    host=$1
    out=reports/$host-$kind.txt
    timeout $limit ssh -o BatchMode=yes -o ConnectTimeout=10 $SSH_OPTS "$host" "$remote" < "$script" > "$out.new" 2> "$out.err"
    if ! grep -q '^== END' "$out.new"; then
        echo "FAILED  $host: $(grep -v '^Warning: Permanently added' "$out.err" | tail -1)" | tee -a "$failed"
        rm -f "$out.new"
    elif [ "$kind" = usage ]; then
        cat "$out.new" >> "reports/usage-$(date +%Y-%m).log"
        rm -f "$out.new"
        echo "ok      $host"
    else
        mv "$out.new" "$out"
        echo "ok      $host"
    fi
    rm -f "$out.err"
}

# 16 servers at a time; each name once, and never one that ssh could read as an option or that leaves reports/
for host in $(sed 's/#.*//' "$hosts" | sort -u); do
    case $host in -* | */*) echo "SKIPPED $host: not a host name" | tee -a "$failed"; continue ;; esac
    run_one "$host" &
    while [ "$(jobs -r | wc -l)" -ge 16 ]; do wait -n; done
done
wait

python3 "$here/summary.py" reports
